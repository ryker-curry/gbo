"""
GBO — Rapsodo Bullpen Analytics: pitch flight-path physics (Phase 4).

compute_trajectory(pitch) returns a sampled (x, y, z, t) flight path
from release to the plate for one RapsodoPitch, cached as JSON on
RapsodoPitch.trajectory_json (see models.py). Pure computation only --
no Streamlit, no database writes -- same house rule as
visualizations/bullpen_charts.py; the caller (an import-time hook or a
backfill script) is responsible for storing the result.

PHYSICS SOURCES -- every constant and equation below is taken directly
from published baseball-aerodynamics research, not invented for this
project:

  - Equations of motion, drag term, and the K = (1/2)*rho*A/m constant:
    Alan M. Nathan, "Analysis of Baseball Trajectories" (2017),
    https://baseball.physics.illinois.edu/TrajectoryAnalysis.pdf,
    Eqs. 1, 7, 8, 9. K = 5.509e-3 ft^-1 for a nominal ball (5-1/8 oz,
    9-1/8 in circumference) and standard sea-level air density
    (1.225 kg/m^3) -- used as-is, since GBO has no per-pitch ball-weight
    or altitude data to refine it further.
  - Drag coefficient CD = 0.40: Alan Nathan & Ike Hall, "Determining the
    Drag Coefficient from PITCHf/x Data," as cited and used directly (in
    the same ft/mph unit system GBO already uses) in Michael Richmond,
    "The effect of air on baseball pitches" (2009),
    http://spiff.rit.edu/richmond/baseball/traj/traj.html -- appropriate
    for the 60-100 mph range relevant to pitching (per that source).
  - g = 32.174 ft/s^2: standard gravitational acceleration, as used in
    Nathan's Eq. 7.

WHY THIS MODEL DOESN'T DERIVE THE MAGNUS FORCE FROM SPIN DIRECTLY:
Nathan's full equations (his Eq. 4/7) compute the Magnus force from the
actual spin vector, which requires trusting a sign convention for which
way spin_axis_degrees maps to a real break direction --
rapsodo_conventions.py explicitly flags that conversion as unconfirmed
against real video (it's only ever been used for on-screen display
before now, never for a physics calculation). Getting that sign wrong
here would make pitches curve the WRONG way on a trajectory chart --
worse than not building this at all. Ryker's call (see chat): instead
of deriving the Magnus force from spin, calibrate the curve to this
pitch's OWN already-measured hb_spin/vb_spin (the same numbers already
shown, trusted, and used on the Movement chart). Concretely:

  1. Gravity and drag are integrated for real via 4th-order Runge-Kutta
     (Nathan's Eqs. 1 and 7, minus the Magnus term) to find the "no-spin"
     trajectory: what this exact pitch's flight would look like with the
     same speed and launch angle, but zero spin. The launch angle itself
     is solved for (a small-angle fixed-point iteration -- see
     _solve_launch_angles) so that the no-spin trajectory lands exactly
     at (plate_x_ft - hb_spin, plate_z_ft - vb_spin) -- i.e., where the
     ball would have crossed the plate MINUS the spin-induced movement
     Rapsodo already measured. This is the same relationship HB/IVB are
     defined by in the first place (deviation from a same-launch,
     zero-spin trajectory), so it's not a new assumption -- it's the
     literal definition of those two fields, run in reverse to recover
     the no-spin path.
  2. The spin-induced curve is added back on top as (t/T)^2 times the
     total measured (hb_spin, vb_spin), where T is total flight time.
     Nathan's own paper (Sec. IV.B/Fig. 4) treats the spin-induced
     transverse acceleration as constant over a pitch's flight (spin
     decay/precession negligible over ~0.4 s -- his estimate is a decay
     time constant "over 20 sec"), and a constant acceleration produces
     displacement proportional to t^2 -- so this isn't an arbitrary
     interpolation curve, it's the standard physical shape for a
     roughly-constant transverse force, just calibrated to this pitch's
     real total measured deflection instead of a spin-rate-derived one.

This means the trajectory's timing and drag-driven speed loss are real
integrated physics; its horizontal/vertical CURVE shape follows the
correct physical form for spin-induced break, but its curve's exact
direction and magnitude come from Rapsodo's own measurement of this
pitch, not from re-deriving it out of spin_axis_degrees.

Requires velocity, release_side, release_height, release_extension,
hb_spin, vb_spin, plate_x_ft, and plate_z_ft all present on the pitch --
returns None (not a guessed/partial trajectory) if any are missing.
"""

import math

from rapsodo_conventions import MOUND_TO_PLATE_FT

G_FT_S2 = 32.174  # standard gravity, ft/s^2 (Nathan Eq. 7)
K_DRAG = 5.509e-3  # (1/2)*rho*A/m for a nominal ball & sea-level air, ft^-1 (Nathan Eq. 8-9)
CD = 0.40  # drag coefficient for pitch-speed range (Nathan & Hall, via Richmond)

MPH_TO_FT_S = 5280.0 / 3600.0
SAMPLE_DT = 0.01  # output sample spacing, seconds -- matches Trackman/Statcast's own reporting cadence (Nathan 2017, Sec. III)
_INTEGRATION_DT = 0.0005  # internal RK4 step -- finer than the output cadence for accuracy, resampled to SAMPLE_DT afterward


def _derivatives(state):
    """state = (x, y, z, vx, vy, vz). Gravity + drag only (Nathan Eq. 7,
    with the Magnus terms omitted -- see module docstring for why)."""
    x, y, z, vx, vy, vz = state
    v = math.sqrt(vx * vx + vy * vy + vz * vz)
    drag = K_DRAG * CD * v
    return (vx, vy, vz, -drag * vx, -drag * vy - G_FT_S2, -drag * vz)


def _rk4_step(state, dt):
    k1 = _derivatives(state)
    s2 = tuple(state[i] + dt / 2 * k1[i] for i in range(6))
    k2 = _derivatives(s2)
    s3 = tuple(state[i] + dt / 2 * k2[i] for i in range(6))
    k3 = _derivatives(s3)
    s4 = tuple(state[i] + dt * k3[i] for i in range(6))
    k4 = _derivatives(s4)
    return tuple(state[i] + dt / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) for i in range(6))


def _integrate(x0, y0, v0, theta, phi, flight_distance, max_time=1.5):
    """Integrates gravity+drag from (x0, y0, z=0) with launch speed v0
    and small angles theta (vertical, radians; positive = up) and phi
    (horizontal, radians; positive = toward +x), until z crosses
    flight_distance. Returns (samples, T, x_final, y_final) where
    samples is a list of (t, x, y, z, vx, vy, vz) at _INTEGRATION_DT
    steps and T/x_final/y_final are linearly interpolated to the exact
    z == flight_distance crossing. Returns None if flight_distance
    isn't reached within max_time (would indicate an unrealistic input,
    not a real pitch -- guards against a runaway loop rather than
    silently returning a wrong answer)."""
    vz0 = v0 * math.cos(theta) * math.cos(phi)
    vx0 = v0 * math.cos(theta) * math.sin(phi)
    vy0 = v0 * math.sin(theta)

    state = (x0, y0, 0.0, vx0, vy0, vz0)
    samples = [(0.0, *state)]
    t = 0.0
    while t < max_time:
        next_state = _rk4_step(state, _INTEGRATION_DT)
        t += _INTEGRATION_DT
        samples.append((t, *next_state))
        if next_state[2] >= flight_distance:
            # Linear interpolation between the last two samples for the
            # exact crossing point -- accurate to well under a
            # millisecond given how fine _INTEGRATION_DT already is.
            t_prev, x_prev, y_prev, z_prev, *_ = samples[-2]
            t_cur, x_cur, y_cur, z_cur, *_ = samples[-1]
            frac = (flight_distance - z_prev) / (z_cur - z_prev) if z_cur != z_prev else 1.0
            T = t_prev + frac * (t_cur - t_prev)
            x_final = x_prev + frac * (x_cur - x_prev)
            y_final = y_prev + frac * (y_cur - y_prev)
            return samples, T, x_final, y_final
        state = next_state
    return None


def _solve_launch_angles(x0, y0, v0, target_x, target_y, flight_distance, iterations=6):
    """Small-angle fixed-point solve for the (theta, phi) launch angles
    that land a gravity+drag-only trajectory at (target_x, target_y) at
    z=flight_distance. Pitch launch angles are always small (a couple
    degrees at most), so a straight-line first guess is already close,
    and each correction step (error in feet, divided by flight_distance,
    added directly to the angle in radians -- valid since for a small
    angle a, tan(a) ~= a) converges in just a few iterations for a
    system this close to linear over ~50-60 ft. Returns
    (theta, phi, samples, T) from the final, converged integration."""
    phi = math.atan2(target_x - x0, flight_distance)
    theta = math.atan2(target_y - y0, flight_distance)

    result = None
    for _ in range(iterations):
        result = _integrate(x0, y0, v0, theta, phi, flight_distance)
        if result is None:
            return None
        samples, T, x_final, y_final = result
        error_x = target_x - x_final
        error_y = target_y - y_final
        phi += error_x / flight_distance
        theta += error_y / flight_distance

    return theta, phi, result[0], result[1]


def compute_trajectory(pitch):
    """Returns the trajectory_json payload for one RapsodoPitch, or None
    if it doesn't have enough data to compute one (never guesses a
    default for a missing physics input -- see module docstring).

    Shape:
      {
        "method": "gravity_drag_rk4_plus_measured_break",
        "flight_time_s": float,
        "flight_distance_ft": float,
        "samples": [
          {"t": 0.0, "x": ..., "y": ..., "z": 0.0, "speed_mph": ...},
          ...  # every SAMPLE_DT seconds, ending at the plate
        ],
      }

    Coordinates (feet): x = horizontal offset, same sign convention as
    release_side/plate_x_ft/hb_spin (0 = mound centerline); y = height
    above ground (0 = ground); z = distance traveled from RELEASE
    toward the plate (0 at release, flight_distance_ft at the plate) --
    note this is release-relative, not Nathan's own home-plate-relative
    z axis; translated here since a flight-path chart reads more
    naturally starting at z=0 for the pitcher's hand.
    """
    required = [
        pitch.velocity, pitch.release_side, pitch.release_height, pitch.release_extension,
        pitch.hb_spin, pitch.vb_spin, pitch.plate_x_ft, pitch.plate_z_ft,
    ]
    if any(v is None for v in required):
        return None

    flight_distance = MOUND_TO_PLATE_FT - float(pitch.release_extension)
    if flight_distance <= 5.0:
        # An extension this large would put release past the plate --
        # not physically sane, treat as bad data rather than integrate
        # something meaningless.
        return None

    x0 = float(pitch.release_side)
    y0 = float(pitch.release_height)
    v0 = float(pitch.velocity) * MPH_TO_FT_S

    hb_spin_ft = float(pitch.hb_spin) / 12.0
    vb_spin_ft = float(pitch.vb_spin) / 12.0
    target_x_nospin = float(pitch.plate_x_ft) - hb_spin_ft
    target_y_nospin = float(pitch.plate_z_ft) - vb_spin_ft

    solved = _solve_launch_angles(x0, y0, v0, target_x_nospin, target_y_nospin, flight_distance)
    if solved is None:
        return None
    theta, phi, raw_samples, T = solved
    if T <= 0:
        return None

    # Resample the fine-grained RK4 output to a clean SAMPLE_DT cadence,
    # adding the calibrated (t/T)^2 spin-curve contribution to each
    # point (see module docstring, step 2).
    output_samples = []
    t = 0.0
    idx = 0
    while t <= T + 1e-9:
        # Advance idx to bracket t within raw_samples (which are at
        # _INTEGRATION_DT spacing, always finer than SAMPLE_DT).
        while idx + 1 < len(raw_samples) - 1 and raw_samples[idx + 1][0] < t:
            idx += 1
        t_prev, x_prev, y_prev, z_prev, vx_prev, vy_prev, vz_prev = raw_samples[idx]
        t_cur, x_cur, y_cur, z_cur, vx_cur, vy_cur, vz_cur = raw_samples[min(idx + 1, len(raw_samples) - 1)]
        frac = (t - t_prev) / (t_cur - t_prev) if t_cur != t_prev else 0.0
        x_nospin = x_prev + frac * (x_cur - x_prev)
        y_nospin = y_prev + frac * (y_cur - y_prev)
        z_val = min(z_prev + frac * (z_cur - z_prev), flight_distance)
        vx = vx_prev + frac * (vx_cur - vx_prev)
        vy = vy_prev + frac * (vy_cur - vy_prev)
        vz = vz_prev + frac * (vz_cur - vz_prev)
        speed_mph = math.sqrt(vx * vx + vy * vy + vz * vz) / MPH_TO_FT_S

        curve_frac = (t / T) ** 2 if T > 0 else 0.0
        output_samples.append({
            "t": round(t, 4),
            "x": round(x_nospin + curve_frac * hb_spin_ft, 4),
            "y": round(y_nospin + curve_frac * vb_spin_ft, 4),
            "z": round(z_val, 4),
            "speed_mph": round(speed_mph, 2),
        })
        t += SAMPLE_DT

    # Always include the exact final plate-crossing point (measured
    # values, not the integrated estimate) as the last sample, so the
    # chart's endpoint always matches plate_x_ft/plate_z_ft exactly --
    # the same point already shown on the Location chart.
    if output_samples[-1]["t"] < T - 1e-6:
        final_speed_mph = math.sqrt(raw_samples[-1][4] ** 2 + raw_samples[-1][5] ** 2 + raw_samples[-1][6] ** 2) / MPH_TO_FT_S
        output_samples.append({
            "t": round(T, 4), "x": round(float(pitch.plate_x_ft), 4), "y": round(float(pitch.plate_z_ft), 4),
            "z": round(flight_distance, 4), "speed_mph": round(final_speed_mph, 2),
        })
    else:
        output_samples[-1]["x"] = round(float(pitch.plate_x_ft), 4)
        output_samples[-1]["y"] = round(float(pitch.plate_z_ft), 4)
        output_samples[-1]["z"] = round(flight_distance, 4)

    return {
        "method": "gravity_drag_rk4_plus_measured_break",
        "flight_time_s": round(T, 4),
        "flight_distance_ft": round(flight_distance, 3),
        "samples": output_samples,
    }
