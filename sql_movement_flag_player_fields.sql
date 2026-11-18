-- Movement Flag: adds 3 new columns to players for the deficit-count
-- flag system (Ryker's own take on a model borrowed from a PT vendor,
-- Aug 2026). Staff set these directly on the player profile; the flag
-- color/score is computed from these + red-status Mobility & ROM rows
-- (see compute_movement_flag in bucket_system.py) -- nothing here is
-- itself the flag, just its two manual inputs.
--
-- Safe to run more than once (IF NOT EXISTS guards).

ALTER TABLE players ADD COLUMN IF NOT EXISTS poor_mover BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE players ADD COLUMN IF NOT EXISTS current_injury BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE players ADD COLUMN IF NOT EXISTS injury_note TEXT;

-- Verify:
-- SELECT player_id, first_name, last_name, poor_mover, current_injury, injury_note FROM players LIMIT 10;
