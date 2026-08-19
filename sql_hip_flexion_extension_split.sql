-- Splits Hip Flexion/Extension into Drive Leg / Plant Leg, matching the
-- rest of the hip block (which was already Drive Leg/Plant Leg for
-- IR/ER/Abduction/Adduction). Run this against the live Supabase DB
-- AFTER deploying the updated app code (seed_lookups.py / bucket_system.py).
--
-- Safe to run more than once -- the INSERTs are guarded with
-- NOT EXISTS checks.

-- 1) Add the 4 new test rows under the same category and roughly the
--    same display_order the old "Hip: Flexion" / "Hip: Extension" rows
--    used, so they sit in the same spot on the entry form.
INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Hip: Drive Leg Flexion', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Hip: Flexion'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Hip: Drive Leg Flexion');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Hip: Plant Leg Flexion', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Hip: Flexion'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Hip: Plant Leg Flexion');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Hip: Drive Leg Extension', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Hip: Extension'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Hip: Drive Leg Extension');

INSERT INTO assessment_test_types (category_id, test_name, unit, display_order)
SELECT category_id, 'Hip: Plant Leg Extension', '°', display_order
FROM assessment_test_types
WHERE test_name = 'Hip: Extension'
  AND NOT EXISTS (SELECT 1 FROM assessment_test_types WHERE test_name = 'Hip: Plant Leg Extension');

-- 2) Check whether the OLD "Hip: Flexion" / "Hip: Extension" rows have
--    any real data recorded against them yet. Run this and read the
--    output before step 3.
SELECT tt.test_name, count(ar.result_id) AS results_recorded
FROM assessment_test_types tt
LEFT JOIN assessment_results ar ON ar.test_type_id = tt.test_type_id
WHERE tt.test_name IN ('Hip: Flexion', 'Hip: Extension')
GROUP BY tt.test_name;

-- 3) If (and ONLY if) both counts above are 0, it's safe to remove the
--    old singular rows -- they're no longer on the entry form as of
--    this change, and nothing references them. Uncomment and run:
--
-- DELETE FROM assessment_test_types WHERE test_name IN ('Hip: Flexion', 'Hip: Extension');
--
-- If either count is NOT 0, some players already have Flexion/Extension
-- values recorded under the old single (not per-leg) fields. Those
-- results aren't lost -- they'll just stop showing on the Mobility &
-- ROM report going forward, since the report only reads the new
-- per-leg test names. Leave the old rows in place (don't delete them)
-- so the historical data stays queryable, and let Ryker decide whether
-- to manually re-enter those players' values under Drive Leg/Plant Leg
-- once known.
