-- Splits Elbow Flexion/Extension into Right/Left, matching Shoulder
-- (bilateral, entered anatomically -- no Drive/Plant-style resolution
-- needed for the elbow, same as shoulder). Run this against the live
-- Supabase DB AFTER deploying the updated app code
-- (seed_lookups.py / bucket_system.py).
--
-- Safe to run more than once -- the INSERTs are guarded with
-- NOT EXISTS checks.

-- 1) Add the 4 new test rows under the same category and roughly the
--    same display_order the old "Elbow: Flexion" / "Elbow: Extension"
--    rows used, so they sit in the same spot on the entry form.
INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Elbow: Right Flexion', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Elbow: Flexion'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Elbow: Right Flexion');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Elbow: Left Flexion', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Elbow: Flexion'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Elbow: Left Flexion');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Elbow: Right Extension', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Elbow: Extension'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Elbow: Right Extension');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Elbow: Left Extension', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Elbow: Extension'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Elbow: Left Extension');

-- 2) Check whether the OLD "Elbow: Flexion" / "Elbow: Extension" rows
--    have any real data recorded against them yet. Run this and read
--    the output before step 3.
SELECT tt.test_name, count(ar.result_id) AS results_recorded
FROM assessment_test_types tt
LEFT JOIN assessment_results ar ON ar.test_type_id = tt.test_type_id
WHERE tt.test_name IN ('Elbow: Flexion', 'Elbow: Extension')
GROUP BY tt.test_name;

-- 3) If (and ONLY if) both counts above are 0, it's safe to remove the
--    old singular rows -- they're no longer on the entry form as of
--    this change, and nothing references them. Uncomment and run:
--
-- DELETE FROM assessment_test_types WHERE test_name IN ('Elbow: Flexion', 'Elbow: Extension');
--
-- If either count is NOT 0, some players already have Flexion/Extension
-- values recorded under the old single (not per-side) elbow fields.
-- Those results aren't lost -- they'll just stop showing on the
-- Mobility & ROM report going forward, since the report only reads the
-- new Right/Left test names. Leave the old rows in place (don't delete
-- them) so the historical data stays queryable, and let Ryker decide
-- whether to manually re-enter those players' values under Right/Left
-- once known.
