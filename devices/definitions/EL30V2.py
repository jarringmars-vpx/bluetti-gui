MODEL_NAME = "EL30V2"
DISPLAY_NAME = "Elite 30 V2"
CAPACITY_WH = 288.0

# Geometry is normalized to the selected 2000x2000 official BLUETTI
# dark-grey straight-on EL30V2 master image.
#
# v0.2.5 retains the first calibration pass. Fine positioning can be adjusted
# here without changing the reusable DeviceVisualWidget.
VISUAL_PROFILE = {
    "display": {
        "fields": {
            "input_watts": {
                "x": 0.428,
                "y": 0.348,
                "width": 0.057,
                "height": 0.044,
                "font_ratio": 0.024,
                "background": "#07100d",
                "background_alpha": 238,
                "color": "#e8fbff",
            },
            "soc": {
                "x": 0.487,
                "y": 0.338,
                "width": 0.064,
                "height": 0.052,
                "font_ratio": 0.031,
                "background": "#07100d",
                "background_alpha": 238,
                "color": "#e8fbff",
            },
            "output_watts": {
                "x": 0.551,
                "y": 0.348,
                "width": 0.060,
                "height": 0.044,
                "font_ratio": 0.024,
                "background": "#07100d",
                "background_alpha": 238,
                "color": "#e8fbff",
            },
            "time_remaining": {
                "x": 0.492,
                "y": 0.390,
                "width": 0.055,
                "height": 0.027,
                "font_ratio": 0.014,
                "background": "#07100d",
                "background_alpha": 238,
                "color": "#d9f8ff",
            },
        }
    },

    "indicators": {
        "dc_output": {
            "x": 0.389,
            "y": 0.475,
            "radius": 0.014,
            "color": "#38ff70",
            "alpha": 80,
            "core_alpha": 120,
        },
        "power": {
            "x": 0.486,
            "y": 0.475,
            "radius": 0.014,
            "color": "#38ff70",
            "alpha": 80,
            "core_alpha": 120,
        },
        "ac_output": {
            "x": 0.581,
            "y": 0.475,
            "radius": 0.014,
            "color": "#38ff70",
            "alpha": 80,
            "core_alpha": 120,
        },
    },
}
