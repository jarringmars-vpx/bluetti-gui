MODEL_NAME = "EL30V2"
DISPLAY_NAME = "Elite 30 V2"
CAPACITY_WH = 288.0

VISUAL_PROFILE = {
    "render_image": "EL30V2_render.png",

    "display": {
        "digit_color": "#F4FBFF",

        "fields": {
            # Left numeric field beneath INPUT W.
            "input_watts": {
                "x": 0.390,
                "y": 0.361,
                "width": 0.057,
                "height": 0.039,
                "digit_height_ratio": 0.78,
                "digit_width_ratio": 0.40,
                "stroke_ratio": 0.068,
                "spacing_ratio": 0.10,
            },

            # Center SOC value inside the gauge.
            "soc": {
                "x": 0.479,
                "y": 0.354,
                "width": 0.043,
                "height": 0.043,
                "digit_height_ratio": 0.82,
                "digit_width_ratio": 0.40,
                "stroke_ratio": 0.068,
                "spacing_ratio": 0.09,
            },

            # Right numeric field beneath OUTPUT W.
            "output_watts": {
                "x": 0.557,
                "y": 0.361,
                "width": 0.057,
                "height": 0.039,
                "digit_height_ratio": 0.78,
                "digit_width_ratio": 0.40,
                "stroke_ratio": 0.068,
                "spacing_ratio": 0.10,
            },

            # Runtime centered below SOC.
            "time_remaining": {
                "x": 0.456,
                "y": 0.407,
                "width": 0.088,
                "height": 0.023,
                "font_ratio": 0.0145,
            },
        },
    },

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
