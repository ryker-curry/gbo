-- Guarantees Right always sorts before Left (and Shoulder -> Elbow ->
-- Hip, matching MOBILITY_ROM_THRESHOLDS' own order) on the Mobility &
-- ROM entry form, regardless of whatever display_order values are
-- currently sitting in the database.
--
-- Why this is needed: the earlier Hip Flexion/Extension and Elbow
-- Flexion/Extension migrations each copied the OLD single field's
-- display_order into BOTH new Right/Left rows -- so e.g. "Elbow: Right
-- Flexion" and "Elbow: Left Flexion" likely share the exact same
-- display_order value. The app's query only sorted by display_order,
-- so a tie like that left the actual on-screen order up to whatever
-- Postgres happened to return, not a guaranteed Right-first order.
-- (The app code has also been updated to add test_type_id as a
-- tiebreaker, but this script fixes the root cause directly so the
-- order is correct and intentional rather than accidentally correct.)
--
-- Safe to run more than once. Only touches the 24 Mobility & ROM
-- fields -- doesn't affect any other category's ordering.
UPDATE assessment_test_types AS t
SET display_order = v.new_order
FROM (VALUES
    ('Shoulder: Right External Rotation', 0),
    ('Shoulder: Left External Rotation', 1),
    ('Shoulder: Right Internal Rotation', 2),
    ('Shoulder: Left Internal Rotation', 3),
    ('Shoulder: Right Flexion', 4),
    ('Shoulder: Left Flexion', 5),
    ('Shoulder: Right Extension', 6),
    ('Shoulder: Left Extension', 7),
    ('Elbow: Right Flexion', 8),
    ('Elbow: Left Flexion', 9),
    ('Elbow: Right Extension', 10),
    ('Elbow: Left Extension', 11),
    ('Hip: Right Internal Rotation', 12),
    ('Hip: Left Internal Rotation', 13),
    ('Hip: Right External Rotation', 14),
    ('Hip: Left External Rotation', 15),
    ('Hip: Right Abduction', 16),
    ('Hip: Left Abduction', 17),
    ('Hip: Right Adduction', 18),
    ('Hip: Left Adduction', 19),
    ('Hip: Right Flexion', 20),
    ('Hip: Left Flexion', 21),
    ('Hip: Right Extension', 22),
    ('Hip: Left Extension', 23)
) AS v(test_name, new_order)
WHERE t.test_name = v.test_name;

-- Verify -- should list all 24 in the exact order above, Right
-- immediately before Left for every pair.
SELECT test_name, display_order
FROM assessment_test_types
WHERE test_name LIKE 'Shoulder:%' OR test_name LIKE 'Elbow:%' OR test_name LIKE 'Hip:%'
ORDER BY display_order;
