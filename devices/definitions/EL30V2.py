MODEL_NAME = "EL30V2"
DISPLAY_NAME = "Elite 30 V2"
CAPACITY_WH = 288.0

VISUAL_PROFILE = {
    "render_image": "EL30V2_render.png",

    "display": {
        "digit_color": "#F4FBFF",

        "fields": {
            # v0.2.10 retains the v0.2.9 leftward LCD corrections.
            "input_watts": {
                "x": 0.388,
                "y": 0.362,
                "width": 0.052,
                "height": 0.038,
                "digit_height_ratio": 0.76,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

            "soc": {
                "x": 0.470,
                "y": 0.359,
                "width": 0.039,
                "height": 0.041,
                "digit_height_ratio": 0.80,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

            "output_watts": {
                "x": 0.535,
                "y": 0.362,
                "width": 0.052,
                "height": 0.038,
                "digit_height_ratio": 0.76,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

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
            "min_green": 38,
            "green_dominance": 6,
            "symbol_green_threshold": 150,
            "symbol_luminance_threshold": 95,
            "glow_neutral_scale": 0.22,
            "glow_residual_green": 0.08,
            "symbol_brightness": 0.62,
            "symbol_green_bias": 10,
        },

        "power": {
            "x": 0.456,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 38,
            "green_dominance": 6,
            "symbol_green_threshold": 150,
            "symbol_luminance_threshold": 95,
            "glow_neutral_scale": 0.22,
            "glow_residual_green": 0.08,
            "symbol_brightness": 0.62,
            "symbol_green_bias": 10,
        },

        "ac_output": {
            "x": 0.551,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 38,
            "green_dominance": 6,
            "symbol_green_threshold": 150,
            "symbol_luminance_threshold": 95,
            "glow_neutral_scale": 0.22,
            "glow_residual_green": 0.08,
            "symbol_brightness": 0.62,
            "symbol_green_bias": 10,
        },
    },
}
