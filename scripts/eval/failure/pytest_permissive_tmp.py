"""Apply the Windows pytest tmp_path ACL workaround for the cross-repo gate."""
import os


if os.name == "nt":
    _original_mkdir = os.mkdir

    def _permissive_mkdir(path, mode=0o777, *args, **kwargs):
        if mode == 0o700:
            mode = 0o755
        return _original_mkdir(path, mode, *args, **kwargs)

    os.mkdir = _permissive_mkdir
