#!/usr/bin/python3

# Script is dummy simulation of pinctrl utility,
# just to make possible gpiocontrol to work on docker's ubuntu.
# Needs files with legal values in /home/ubuntu/gpio/ to work properly
# - done by install.sh script during docker image build

import argparse

GPIO_DIR = '/home/ubuntu/gpio'

STATE_DICT = {
    'dh': 'hi',
    'dl': 'lo'
}


def main():
    parser = argparse.ArgumentParser(description="Dummy pinctrl")
    parser.add_argument('command', help='Command: get or set',
                        choices=['get', 'set'])
    parser.add_argument('pin_number', help='Pin number', type=int,
                        choices=range(1, 28))
    parser.add_argument('operation', help="Operation - script doesn't use it",
                        nargs='?')
    parser.add_argument('state', help='State', choices=['dh', 'dl'],
                        nargs='?')
    args = parser.parse_args()

    if args.command == 'get':
        print(get(args.pin_number))
    elif args.command == 'set':
        set(args.pin_number, STATE_DICT[args.state])
    else:
        print("Unknown command")


def get(pin_number):
    with open(f'{GPIO_DIR}/{pin_number}', 'r') as f:
        state = f.read().strip()
        return f"{pin_number}: op -- pd | {state} // GPIO26 = output"


def set(pin_number, state):
    with open(f'{GPIO_DIR}/{pin_number}', 'w') as f:
        f.write(state)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"pinctrl error {e}")
        raise e
