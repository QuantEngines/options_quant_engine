from config.settings import TARGET_PROFIT_PERCENT, STOP_LOSS_PERCENT


def calculate_exit(
    entry_price,
    target_profit_percent=TARGET_PROFIT_PERCENT,
    stop_loss_percent=STOP_LOSS_PERCENT,
):

    target = entry_price * (1 + target_profit_percent / 100)

    stop = entry_price * (1 - stop_loss_percent / 100)

    return target, stop
