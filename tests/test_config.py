import json
import pytest
from floodcat.core.config import DEFAULT_CONFIG_PATH, load_config
from floodcat.core.errors import ModelError


def test_default_config_is_the_json_file(config):
    assert (
        config.to_dict()["max_depth_m"]
        == json.loads(DEFAULT_CONFIG_PATH.read_text())["max_depth_m"]
    )


@pytest.mark.parametrize("cap", [0.79, 0.96, 1.0])
def test_damage_cap_must_stay_within_80_to_95_percent(config, cap):
    adjustments = {
        **config.class_adjustments,
        "concrete_rcc": {"jrc_depth_scale": 1.3, "damage_cap": cap},
    }
    with pytest.raises(ModelError):
        config.replace(class_adjustments=adjustments)


def test_inverted_return_periods_rejected(config):
    with pytest.raises(ModelError):
        config.replace(return_periods={**config.return_periods, "extreme": 500.0})


def test_aal_zero_point_must_be_more_frequent_than_first_tier(config):
    with pytest.raises(ModelError):
        config.replace(aal_zero_loss_return_period=10.0)


def test_unknown_field_rejected(tmp_path, config):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({**config.to_dict(), "surprise": 1}))
    with pytest.raises(ModelError):
        load_config(path)
