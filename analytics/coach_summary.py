"""
GBO -- Coach Summary (Oct 2026, Ryker: "act like you are a pitching coach
... is what we currently have useful and easy to understand?"). The default
Pitcher Deep Dive view: the handful of things a coach needs before opening
any other view, in the same plain voice as the Pitcher Report.

Pulls from pieces that already exist -- no new math:
  * player_report.range_report  key numbers vs goal / D2 / team, plus the
                                "what went well / work on" lines
  * results_view.scorecard      best / weakest pitch by results
  * arsenal_plan.build_plan     the biggest shape change to chase
  * pitch_insights.get_ahead    what strike one is worth to him
"""

from analytics import player_report, results_view, pitch_insights

KEY_TILES = ("strike_pct", "fps_pct", "k_pct", "bb_pct", "whiff_pct", "execution_pct")
MIN_PITCH_N = 15


def _rate(v, d=3):
    return "—" if v is None else (f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}")


def best_and_worst(card):
    rows = [r for r in card["rows"] if r["n"] >= MIN_PITCH_N and r["rv100"] is not None]
    if len(rows) < 2:
        return None, None
    best = min(rows, key=lambda r: r["rv100"])
    worst = max(rows, key=lambda r: r["rv100"])
    return best, (worst if worst is not best and worst["rv100"] > 0 else None)


def pitch_line(r, best=True):
    w, avg, hard = r.get("whiff"), r.get("avg"), (r.get("hard") if r.get("bip") else None)
    if best:
        bits = []
        if w is not None and w >= 15:
            bits.append(f"{w:.0f}% of swings missed")
        if avg is not None:
            bits.append(f"hitters hit {_rate(avg)} off it")
        if hard is not None:
            bits.append(f"{hard:.0f}% hit hard")
        return f"{r['type']} -- {', '.join(bits)}. His best results right now; lean on it when he needs an out."
    contact = ", ".join(x for x in ([f"hitters hit {_rate(avg)}"] if avg is not None else [])
                        + ([f"{hard:.0f}% hit hard"] if hard is not None else []))
    if w is not None and w >= 25:
        return (f"{r['type']} -- still misses bats ({w:.0f}% of swings), but when hitters connect they do damage "
                f"({contact}). Usually a location problem -- see Results and Command.")
    return f"{r['type']} -- {contact}. Hitters do the most damage on it right now."


def build(db, pid, game_ids, label, mine, team, loc, raps=None, throws=None, arm=None, rel_h=None, overrides=None):
    """mine/team: GamePitch lists (date range); loc: {game_pitch_id: (x, z)}."""
    rep = player_report.range_report(db, pid, game_ids, label) if game_ids else None
    out = {"tiles": [], "good": [], "bad": [], "best": None, "worst": None, "arsenal": None, "n": len(mine)}
    if rep:
        rows = {r["key"]: r for r in rep["rows"]}
        out["tiles"] = [rows[k] for k in KEY_TILES if k in rows]
        out["good"] = [g for g in rep["good"] if not g.startswith("Nothing")]
        out["bad"] = [b for b in rep["bad"] if not b.startswith("Nothing")]
        out["ip"] = rep["you"].get("ip_display") if rep.get("you") else None
        out["bf"] = rep["you"].get("bf") if rep.get("you") else None
    if mine:
        card = results_view.scorecard(mine, team, loc)
        b, w = best_and_worst(card)
        out["best"] = pitch_line(b) if b else None
        out["worst"] = pitch_line(w, best=False) if w else None
        g = pitch_insights.get_ahead(mine, loc)
        if g["gap"] is not None and g["ahead"]["pa"] >= 8 and g["behind"]["pa"] >= 8:
            if g["gap"] < 5:
                out["bad"].append(f"Getting ahead isn't turning into strikeouts yet ({g['ahead']['k']:.0f}% K after 0-1). "
                                  "Work on the 0-1 and 1-2 put-away pitch.")
            elif g["gap"] >= 15:
                out["good"].append(f"Strike one turns into strikeouts: {g['ahead']['k']:.0f}% K after 0-1 vs "
                                   f"{g['behind']['k']:.0f}% after 1-0.")
    if raps:
        from analytics import arsenal_plan
        from analytics.bullpen_metrics import pitch_type_label
        plan = arsenal_plan.build_plan(raps, throws or "R", arm, rel_h, overrides=overrides, label_of=pitch_type_label)
        if plan:
            tunes = sorted([r for r in plan["rows"] if r["status"] == "tune"], key=lambda r: -(r["dist"] or 0))
            if tunes:
                t = tunes[0]
                out["arsenal"] = f"{t['label']}: {t['text'].replace('To reach the target: ', '').rstrip('.')}."
            elif plan["adds"]:
                a = next((x for x in plan["adds"] if x["core"]), plan["adds"][0])
                out["arsenal"] = f"Add a {a['label'].lower()}: {a['why']}"
    out["good"] = out["good"][:4]
    out["bad"] = out["bad"][:4]
    return out
