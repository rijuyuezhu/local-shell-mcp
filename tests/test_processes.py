from workgate.utils.processes import new_process_group_kwargs


def test_new_process_group_kwargs_uses_posix_session() -> None:
    assert new_process_group_kwargs(windows=False) == {
        "start_new_session": True
    }


def test_new_process_group_kwargs_uses_windows_creation_flag() -> None:
    assert new_process_group_kwargs(
        windows=True,
        windows_creation_flag=512,
    ) == {"creationflags": 512}
