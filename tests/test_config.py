from copy import deepcopy

import pytest
import tomli_w

from config import DEFAULT_CONFIG, DEFAULT_CONFIG_TOML, ConfigError, ConfigManager


def test_invalid_toml_is_rejected(config_manager):
    with pytest.raises(ConfigError, match="invalid TOML"):
        config_manager.parse(b"invalid = [")


def test_default_toml_matches_default_config(config_manager):
    """The shipped TOML literal and the schema dict must not drift apart."""
    assert config_manager.parse(DEFAULT_CONFIG_TOML.encode("utf-8")) == DEFAULT_CONFIG


def test_missing_required_section_is_rejected(config_manager):
    with pytest.raises(ConfigError, match="missing required section"):
        config_manager.parse(b"[server]\nhost = \"0.0.0.0\"\n")


def test_missing_page_drop_servo_is_rejected(config_manager, config):
    changed = deepcopy(config)
    changed["servos"].pop("page_drop")

    with pytest.raises(ConfigError, match="servos.page_drop is required"):
        config_manager._validate(changed)


def test_valid_named_servo_config_loads(config):
    assert config["servos"]["page_drop"]["pin"] == 12
    assert config["servos"]["page_clamp_big"]["pin"] == 19
    assert config["servos"]["page_clamp_small"]["pin"] == 27
    assert config["servos"]["page_drop"]["pin_factory"] == "pigpio"


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("motor", "step_pin", 22),
        ("motor", "dir_pin", 23),
        ("motor", "enable_pin", 24),
        ("motor2", "step_pin", 17),
        ("motor2", "dir_pin", 5),
        ("motor2", "enable_pin", 6),
        ("fan", "pin", 13),
        ("fan", "tach_pin", 22),
    ],
)
def test_pin_changes_require_restart(config_manager, config, section, field, value):
    changed = deepcopy(config)
    changed[section][field] = value

    assert config_manager.restart_required(config, changed) is True


def test_servo_pin_changes_require_restart(config_manager, config):
    changed = deepcopy(config)
    changed["servos"]["page_drop"]["pin"] = 13

    assert config_manager.restart_required(config, changed) is True


def test_new_servo_pin_requires_restart(config_manager, config):
    changed = deepcopy(config)
    changed["servos"]["left_assist"] = deepcopy(config["servos"]["page_drop"])
    changed["servos"]["left_assist"]["pin"] = 16

    assert config_manager.restart_required(config, changed) is True


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("camera", "lens_position", 1.1),
        ("server", "port", 9000),
        ("workflow", "servo_down_pause", 0.5),
        ("motor", "step_delay", 0.002),
        ("motor2", "step_delay", 0.004),
        ("fan", "min_start_duty_pct", 15),
    ],
)
def test_non_pin_changes_do_not_require_restart(config_manager, config, section, field, value):
    changed = deepcopy(config)
    changed[section][field] = value

    assert config_manager.restart_required(config, changed) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("down_angle", 90),
        ("default_settle_time", 0.2),
    ],
)
def test_servo_non_pin_changes_do_not_require_restart(config_manager, config, field, value):
    changed = deepcopy(config)
    changed["servos"]["page_drop"][field] = value

    assert config_manager.restart_required(config, changed) is False


def test_servo_live_changes_are_reported(config_manager, config):
    changed = deepcopy(config)
    changed["servos"]["page_drop"]["down_angle"] = 90

    assert config_manager.applied_live_sections(config, changed) == ["servos.page_drop"]


@pytest.mark.parametrize("frequency", [11999, 50001])
def test_fan_frequency_outside_supported_range_is_rejected(
    config_manager, config, frequency
):
    changed = deepcopy(config)
    changed["fan"]["frequency_hz"] = frequency

    with pytest.raises(ConfigError, match="fan.frequency_hz"):
        config_manager._validate(changed)


def test_fan_default_changes_are_reported_live(config_manager, config):
    changed = deepcopy(config)
    changed["fan"]["min_start_duty_pct"] = 15

    assert config_manager.applied_live_sections(config, changed) == ["fan.defaults"]


def test_valid_upload_creates_backup(config_manager, config_dict):
    config_dict["workflow"]["servo_up_pause"] = 2.5

    config = config_manager.save_uploaded(tomli_w.dumps(config_dict).encode("utf-8"))

    assert config["workflow"]["servo_up_pause"] == 2.5
    assert list(config_manager.path.parent.glob("config.toml.*.bak"))


def test_missing_small_clamp_servo_is_rejected(config_manager, config):
    """The page turn drives it now, so it is no longer optional."""
    changed = deepcopy(config)
    changed["servos"].pop("page_clamp_small")

    with pytest.raises(ConfigError, match="servos.page_clamp_small is required"):
        config_manager._validate(changed)


def test_hold_angle_outside_the_servo_range_is_rejected(config_manager, config):
    """gpiozero raises mid-move on an out-of-range angle, with the arm down.

    Caught at config time instead, the same way the bench script checks up
    front rather than discovering it halfway through a page turn.
    """
    changed = deepcopy(config)
    changed["servos"]["page_clamp_small"]["hold_angle"] = 200

    with pytest.raises(ConfigError, match="hold_angle"):
        config_manager._validate(changed)


def test_contact_angle_outside_the_servo_range_is_rejected(config_manager, config):
    changed = deepcopy(config)
    changed["servos"]["page_clamp_big"]["contact_angle"] = -5

    with pytest.raises(ConfigError, match="contact_angle"):
        config_manager._validate(changed)


def test_return_shortfall_larger_than_the_outward_run_is_rejected(
    config_manager, config
):
    """A shortfall past the outward total would drive the wheel back past home."""
    changed = deepcopy(config)
    motor = changed["motor"]
    motor["return_short_degrees"] = (
        motor["page_turn_degrees"] + motor["shared_degrees"] + 1
    )

    with pytest.raises(ConfigError, match="return_short_degrees"):
        config_manager._validate(changed)


def test_zero_return_shortfall_is_allowed(config_manager, config):
    """0 is the exact round trip, and must stay reachable."""
    changed = deepcopy(config)
    changed["motor"]["return_short_degrees"] = 0
    changed["motor2"]["return_short_degrees"] = 0

    config_manager._validate(changed)


@pytest.mark.parametrize("mode", ["motor2_only", "shared"])
def test_page_turn_sequence_modes_are_allowed(config_manager, config, mode):
    changed = deepcopy(config)
    changed["workflow"]["turn_sequence"] = mode

    config_manager._validate(changed)


def test_unknown_page_turn_sequence_is_rejected(config_manager, config):
    changed = deepcopy(config)
    changed["workflow"]["turn_sequence"] = "parallel"

    with pytest.raises(ConfigError, match="workflow.turn_sequence"):
        config_manager._validate(changed)


@pytest.mark.parametrize("degrees", [0.0, 45.0, 90.0])
def test_motor_two_preposition_within_first_leg_is_allowed(
    config_manager, config, degrees
):
    changed = deepcopy(config)
    changed["motor2"]["preposition_degrees"] = degrees

    config_manager._validate(changed)


@pytest.mark.parametrize("degrees", [-0.1, 90.1])
def test_motor_two_preposition_outside_first_leg_is_rejected(
    config_manager, config, degrees
):
    changed = deepcopy(config)
    changed["motor2"]["preposition_degrees"] = degrees

    with pytest.raises(ConfigError, match="motor2.preposition_degrees"):
        config_manager._validate(changed)


def test_fan_duty_outside_percent_range_is_rejected(config_manager, config):
    changed = deepcopy(config)
    changed["fan"]["duty_pct"] = 150

    with pytest.raises(ConfigError, match="duty_pct"):
        config_manager._validate(changed)


def test_obstruction_confidence_outside_zero_to_one_is_rejected(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["min_confidence"] = 1.5

    with pytest.raises(ConfigError, match="min_confidence"):
        config_manager._validate(changed)


def test_obstruction_mode_is_validated(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["mode"] = "unsupported"

    with pytest.raises(ConfigError, match="mode"):
        config_manager._validate(changed)


def test_candidate_presence_cannot_exceed_confirmation(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["min_candidate_presence_confidence"] = 0.75
    changed["obstruction"]["min_presence_confidence"] = 0.5

    with pytest.raises(ConfigError, match="min_candidate_presence_confidence"):
        config_manager._validate(changed)


def test_obstruction_change_requires_restart(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["min_confidence"] = 0.4

    assert config_manager.restart_required(config, changed)


def test_lores_stream_change_requires_restart(config_manager, config):
    changed = deepcopy(config)
    changed["camera"]["lores_width"] = 800

    assert config_manager.restart_required(config, changed)


def test_polling_slower_than_the_staleness_cutoff_is_rejected(config_manager, config):
    """Every reading would age out before the next arrived.

    The gate would then sit permanently shut on a rig that is working, which is
    a config mistake worth catching at load rather than on the bench.
    """
    changed = deepcopy(config)
    changed["obstruction"]["target_interval"] = 5.0
    changed["obstruction"]["stale_after_seconds"] = 3.0

    with pytest.raises(ConfigError, match="stale"):
        config_manager._validate(changed)


def test_clear_frames_must_be_at_least_one(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["clear_frames"] = 0

    with pytest.raises(ConfigError, match="clear_frames"):
        config_manager._validate(changed)


def test_lores_dimensions_are_validated(config_manager, config):
    changed = deepcopy(config)
    changed["camera"]["lores_width"] = 0

    with pytest.raises(ConfigError, match="lores_width"):
        config_manager._validate(changed)


def test_obstruction_source_must_match_the_camera_stream(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["source_width"] = 640

    with pytest.raises(ConfigError, match="source size"):
        config_manager._validate(changed)


@pytest.mark.parametrize(
    "roi",
    [
        [-0.1, 0.0, 1.0, 1.0],
        [0.5, 0.0, 0.5, 1.0],
        [0.0, 0.0, 1.1, 1.0],
        [0.0, 0.0, 1.0],
    ],
)
def test_bed_roi_is_normalized_and_ordered(config_manager, config, roi):
    changed = deepcopy(config)
    changed["obstruction"]["bed_roi"] = roi

    with pytest.raises(ConfigError, match="bed_roi"):
        config_manager._validate(changed)


def test_region_schedule_must_include_a_full_frame(config_manager, config):
    changed = deepcopy(config)
    changed["obstruction"]["region_schedule"] = ["bed", "bed"]

    with pytest.raises(ConfigError, match="include 'full'"):
        config_manager._validate(changed)


def test_exposure_mode_is_validated(config_manager, config):
    changed = deepcopy(config)
    changed["camera"]["exposure_mode"] = "very-short"

    with pytest.raises(ConfigError, match="exposure_mode"):
        config_manager._validate(changed)
