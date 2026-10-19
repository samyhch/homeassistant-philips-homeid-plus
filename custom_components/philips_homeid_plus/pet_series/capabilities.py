"""Conservative hardware capabilities, independent of cloud availability."""

CAMERA_DATAPOINTS = frozenset({"103", "104", "105", "106", "108", "188", "134", "233"})


def supports_camera(device):
    """Exclude the camera-less PAW3320; preserve unknown models' behavior.

    Do not infer missing hardware from an empty/transient cloud response.
    Product CTNs may include a regional suffix such as /02.
    """
    model = str(getattr(device, "product_ctn", "") or "").strip().upper().split("/")[0]
    return model != "PAW3320"


def supports_datapoint(device, dp_id):
    """Filter only known camera-only controls, not optional feeding settings."""
    return str(dp_id) not in CAMERA_DATAPOINTS or supports_camera(device)
