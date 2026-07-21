"""Regression tests for portable chain-simulator startup arguments."""

import pytest

from tools.chain_simulator_connector import build_chain_simulator_entrypoint_args


def test_normal_start_omits_initial_epoch_and_supernova_arguments():
    arguments = build_chain_simulator_entrypoint_args(
        block=31_074_633,
        round_number=31_105_820,
        epoch=0,
        environment={},
    )

    assert "--initial-nonce=31074633" in arguments
    assert "--initial-round=31105820" in arguments
    assert not any(argument.startswith("--initial-epoch=") for argument in arguments)
    assert not any("supernova" in argument for argument in arguments)


def test_nonzero_initial_epoch_requires_explicit_supernova_opt_in():
    with pytest.raises(ValueError, match="MX_RUN_SUPERNOVA_TESTS"):
        build_chain_simulator_entrypoint_args(
            block=1,
            round_number=1,
            epoch=2_168,
            environment={},
        )


def test_opted_in_supernova_start_includes_explicit_chronology():
    arguments = build_chain_simulator_entrypoint_args(
        block=31_200_412,
        round_number=31_231_946,
        epoch=2_168,
        environment={
            "MX_RUN_SUPERNOVA_TESTS": "1",
            "MX_CHAIN_SIM_ROUNDS_PER_EPOCH": "14400",
            "MX_CHAIN_SIM_SUPERNOVA_ROUNDS_PER_EPOCH": "144000",
            "MX_CHAIN_SIM_ROUND_DURATION": "6000",
            "MX_CHAIN_SIM_SUPERNOVA_ROUND_DURATION": "600",
        },
    )

    assert "--initial-epoch=2168" in arguments
    assert "--supernova-rounds-per-epoch=144000" in arguments
    assert "--supernova-round-duration=600" in arguments
