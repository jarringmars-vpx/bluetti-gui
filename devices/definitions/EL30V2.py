MODEL_NAME = "EL30V2"
DISPLAY_NAME = "Elite 30 V2"
CAPACITY_WH = 288.0

VISUAL_PROFILE = {
    "render_image": "EL30V2_render.png",

    "display": {
        "digit_color": "#F4FBFF",

        "fields": {
            # Maximized-view calibration:
            # input moved slightly right and reduced a touch.
            "input_watts": {
                "x": 0.397,
                "y": 0.362,
                "width": 0.052,
                "height": 0.038,
                "digit_height_ratio": 0.76,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

            # SOC moved slightly right/down and reduced.
            "soc": {
                "x": 0.484,
                "y": 0.359,
                "width": 0.039,
                "height": 0.041,
                "digit_height_ratio": 0.80,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

            # Output moved left noticeably toward the center gauge.
            "output_watts": {
                "x": 0.548,
                "y": 0.362,
                "width": 0.052,
                "height": 0.038,
                "digit_height_ratio": 0.76,
                "digit_width_ratio": 0.39,
                "stroke_ratio": 0.066,
                "spacing_ratio": 0.09,
            },

            # Runtime was already close in v0.2.7; retain nearly the same fit.
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
            "min_green": 40,
            "green_dominance": 6,
            "off_neutral_scale": 0.30,
            "off_residual_green": 0.12,
        },

        "power": {
            "x": 0.456,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 40,
            "green_dominance": 6,
            "off_neutral_scale": 0.30,
            "off_residual_green": 0.12,
        },

        "ac_output": {
            "x": 0.551,
            "y": 0.448,
            "width": 0.060,
            "height": 0.064,
            "min_green": 40,
            "green_dominance": 6,
            "off_neutral_scale": 0.30,
            "off_residual_green": 0.12,
        },
    },
}
