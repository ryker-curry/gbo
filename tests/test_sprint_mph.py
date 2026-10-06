from bucket_system import sprint_mph, flying_10_mph, FLYING_10_TEST_NAME, THIRTY_YARD_TEST_NAME


def test_sprint_mph():
    assert sprint_mph(FLYING_10_TEST_NAME, 1.0) == flying_10_mph(1.0) == 20.5
    assert sprint_mph(THIRTY_YARD_TEST_NAME, 4.0) == 15.3
    assert sprint_mph("Acceleration: 10-Yard Sprint Time", 1.7) == 12.0
    assert sprint_mph("Body Fat %", 12.0) is None
    assert sprint_mph(THIRTY_YARD_TEST_NAME, 0) is None and sprint_mph(THIRTY_YARD_TEST_NAME, None) is None
