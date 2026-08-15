import pytest

from gtfs_explorer.application.ui_state import UiAction, UiMode, UiState


def test_actions_follow_the_global_state_transitions() -> None:
    state = UiState()
    assert state.allows(UiAction.OPEN_PROJECT)
    assert not state.allows(UiAction.IMPORT_FEED)

    state = state.project_opened()
    assert state.mode is UiMode.PROJECT_READY
    assert state.allows(UiAction.IMPORT_FEED)

    state = state.job_started()
    assert state.mode is UiMode.JOB_RUNNING
    assert state.allows(UiAction.CANCEL_JOB)
    assert not state.allows(UiAction.OPEN_PROJECT)

    state = state.cancellation_requested()
    assert state.mode is UiMode.JOB_CANCELLING
    assert not state.allows(UiAction.CANCEL_JOB)

    state = state.job_finished()
    assert state.mode is UiMode.PROJECT_READY


def test_recovery_blocks_import_and_job_transition_requires_ready_project() -> None:
    recovery = UiState().project_opened(recovery_required=True)
    assert recovery.mode is UiMode.RECOVERY_REQUIRED
    assert not recovery.allows(UiAction.IMPORT_FEED)
    with pytest.raises(RuntimeError, match="iniciar un trabajo"):
        recovery.job_started()
