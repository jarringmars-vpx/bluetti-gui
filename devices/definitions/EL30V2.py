MODEL_NAME = "EL30V2"
DISPLAY_NAME = "Elite 30 V2"
CAPACITY_WH = 288.0

# Digital-twin visual profile for the selected 2000x2000 EL30V2 render base.
#
# All coordinates are normalized to source-image dimensions, allowing the same
# profile to remain valid regardless of how large the widget is displayed.
VISUAL_PROFILE = {
    "render_image": "EL30V2_render.png",

    "display": {
        "digit_color": "#F4FBFF",

        "fields": {
            # Existing permanent INPUT/W label remains in the image.
            # Only the live number is painted beneath it.
            "input_watts": {
                "x": 0.382,
                "y": 0.350,
                "width": 0.071,
                "height": 0.052,
                "digit_height_ratio": 0.86,
                "spacing_ratio": 0.10,
            },

            # SOC sits inside the center of the blue circular gauge.
            "soc": {
                "x": 0.469,
                "y": 0.346,
                "width": 0.067,
                "height": 0.060,
                "digit_height_ratio": 0.93,
                "spacing_ratio": 0.10,
            },

            # Existing permanent OUTPUT/W label remains in the image.
            "output_watts": {
                "x": 0.552,
                "y": 0.350,
                "width": 0.071,
                "height": 0.052,
                "digit_height_ratio": 0.86,
                "spacing_ratio": 0.10,
            },

            # Runtime is centered below the SOC value.
            "time_remaining": {
                "x": 0.449,
                "y": 0.402,
                "width": 0.107,
                "height": 0.031,
                "font_ratio": 0.0175,
            },
        },
    },

    # Tight button rectangles. ON uses the original photographed green pixels.
    # OFF selectively darkens only green pixels inside the corresponding area.
    "buttons": {
        "dc_output": {
            "x": 0.359,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 55,
            "green_dominance": 12,
            "off_brightness_scale": 0.38,
            "off_green_scale": 0.48,
        },

        "power": {
            "x": 0.456,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 55,
            "green_dominance": 12,
            "off_brightness_scale": 0.38,
            "off_green_scale": 0.48,
        },

        "ac_output": {
            "x": 0.551,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 55,
            "green_dominance": 12,
            "off_brightness_scale": 0.38,
            "off_green_scale": 0.48,
        },
    },
}
