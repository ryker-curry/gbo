-- Renames the 6 hip ROM entry fields from Drive Leg/Plant Leg naming
-- back to Right/Left naming -- per Ryker's follow-up call, Drive/Plant
-- is the right framing for INTERPRETING a hip ROM result (that's what
-- the app's report still shows), but it was confusing to actually type
-- in at assessment time. Run this against the live Supabase DB AFTER
-- deploying the updated app code (seed_lookups.py / bucket_system.py).
--
-- This is a straight RENAME, not an add/remove like the last ROM
-- migration -- any values already entered under the Drive Leg/Plant
-- Leg names are preserved and simply become associated with the new
-- Right/Left name. IMPORTANT: renaming "Hip: Drive Leg X" to
-- "Hip: Right X" is only correct for a RIGHT-handed player (drive leg
-- = throwing-side leg = right leg for a righty) -- if any left-handed
-- pitchers already have hip ROM values entered under the old Drive
-- Leg/Plant Leg names, this rename would silently swap their Right/
-- Left sides. Check the count query below FIRST and read the note
-- before running the renames.

-- 1) Check whether any hip ROM values have been recorded yet at all,
--    broken out by test name. Run this and read the output before
--    step 2.
SELECT tt.test_name, count(ar.result_id) AS results_recorded
FROM assessment_test_types tt
LEFT JOIN assessment_results ar ON ar.test_type_id = tt.test_type_id
WHERE tt.test_name IN (
    'Hip: Drive Leg Internal Rotation', 'Hip: Plant Leg Internal Rotation',
    'Hip: Drive Leg External Rotation', 'Hip: Plant Leg External Rotation',
    'Hip: Drive Leg Abduction', 'Hip: Plant Leg Abduction',
    'Hip: Drive Leg Adduction', 'Hip: Plant Leg Adduction',
    'Hip: Drive Leg Flexion', 'Hip: Plant Leg Flexion',
    'Hip: Drive Leg Extension', 'Hip: Plant Leg Extension'
)
GROUP BY tt.test_name;

-- 2) If ALL counts above are 0 (most likely, since this whole hip ROM
--    block was only just added), it's simplest and safest to just
--    rename every row -- no player data to worry about mixing up.
--    Run this block as-is:
UPDATE assessment_test_types SET test_name = 'Hip: Right Internal Rotation' WHERE test_name = 'Hip: Drive Leg Internal Rotation';
UPDATE assessment_test_types SET test_name = 'Hip: Left Internal Rotation'  WHERE test_name = 'Hip: Plant Leg Internal Rotation';
UPDATE assessment_test_types SET test_name = 'Hip: Right External Rotation' WHERE test_name = 'Hip: Drive Leg External Rotation';
UPDATE assessment_test_types SET test_name = 'Hip: Left External Rotation'  WHERE test_name = 'Hip: Plant Leg External Rotation';
UPDATE assessment_test_types SET test_name = 'Hip: Right Abduction' WHERE test_name = 'Hip: Drive Leg Abduction';
UPDATE assessment_test_types SET test_name = 'Hip: Left Abduction'  WHERE test_name = 'Hip: Plant Leg Abduction';
UPDATE assessment_test_types SET test_name = 'Hip: Right Adduction' WHERE test_name = 'Hip: Drive Leg Adduction';
UPDATE assessment_test_types SET test_name = 'Hip: Left Adduction'  WHERE test_name = 'Hip: Plant Leg Adduction';
UPDATE assessment_test_types SET test_name = 'Hip: Right Flexion' WHERE test_name = 'Hip: Drive Leg Flexion';
UPDATE assessment_test_types SET test_name = 'Hip: Left Flexion'  WHERE test_name = 'Hip: Plant Leg Flexion';
UPDATE assessment_test_types SET test_name = 'Hip: Right Extension' WHERE test_name = 'Hip: Drive Leg Extension';
UPDATE assessment_test_types SET test_name = 'Hip: Left Extension'  WHERE test_name = 'Hip: Plant Leg Extension';

-- 3) If step 1 showed any non-zero counts, STOP -- don't run the
--    UPDATEs above blindly. That means at least one player already has
--    a hip ROM value recorded, and for a left-handed player "Drive
--    Leg" is their LEFT leg, not their right -- a blanket rename would
--    silently put that value under the wrong side. In that case, come
--    back and we'll write a rename that checks each player's Player.
--    throws before deciding Right vs. Left, instead of a flat rename.
