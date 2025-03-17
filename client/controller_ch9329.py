import random
import threading
from abc import ABC, abstractmethod

import pych9329.exceptions
from pych9329 import keyboard
from pych9329 import mouse
from pych9329 import chip_command
from loguru import logger
from serial import Serial, SerialException

from data.hex_data import HexData
from data.keyboard_ch9329_hid_map import CH9329_HID_MAP


class ControllerBase(ABC):
    @abstractmethod
    def create_connection(self) -> bool:
        pass

    @abstractmethod
    def close_connection(self) -> None:
        pass

    def reset_connection(self) -> bool:
        self.close_connection()
        return self.create_connection()

    @abstractmethod
    def check_connection(self) -> bool:
        pass

    @abstractmethod
    def mouse_send_data(
        self,
        button_name: str,
        x: int = 0,
        y: int = 0,
        wheel: int = 0,
        relative: bool = False,
    ):
        pass

    @abstractmethod
    def keyboard_send_data(self, keys: list, function_keys: list):
        pass

    @abstractmethod
    def keyboard_receive_status(self) -> tuple[bool, int]:
        pass

    @abstractmethod
    def release(self, release_type: str) -> None:
        pass


class ControllerCh9329(ControllerBase):
    def __init__(
        self,
        controller_port: str = "COM1",
        baud: int = 9600,
        screen_x: int = 1920,
        screen_y: int = 1080,
    ):
        self.connection_mutex: threading.Lock = threading.Lock()
        self.connection: Serial | None = None
        self.ch9329_hid_map: dict = CH9329_HID_MAP
        self.port: str = controller_port
        self.baud: int = baud
        self.screen_x: int = screen_x
        self.screen_y: int = screen_y
        self.min_interval: float = 0.2
        self.max_interval: float = 0.5
        self.timeout: float = 0.5

    def get_connection_params(self) -> tuple[str, int, int, int]:
        return self.port, self.baud, self.screen_x, self.screen_y

    def set_connection_params(
        self,
        controller_port: str = "COM1",
        baud: int = 9600,
        screen_x: int = 1920,
        screen_y: int = 1080,
    ):
        self.port: str = controller_port
        self.baud: int = baud
        self.screen_x: int = screen_x
        self.screen_y: int = screen_y

    def create_connection(self) -> bool:
        connection_status: bool = False
        if self.port == "":
            return connection_status
        if self.connection is not None:
            self.close_connection()
        with self.connection_mutex:
            try:
                self.connection = Serial(
                    self.port, self.baud, timeout=self.timeout
                )
                connection_status = True
            except SerialException:
                self.connection = None
        return connection_status

    def close_connection(self):
        with self.connection_mutex:
            if self.connection is not None:
                self.connection.close()
            self.connection = None

    def reset_connection(self):
        logger.debug("reset_connection")
        self.close_connection()
        self.create_connection()

    def check_connection(self) -> bool:
        with self.connection_mutex:
            if self.connection is not None:
                if self.connection.is_open is True:
                    return True
            return False

    def random_interval(self) -> float:
        return random.uniform(self.min_interval, self.max_interval)

    # 获取产品信息
    def product_info(self) -> str:
        info = ""
        with self.connection_mutex:
            if self.connection is None:
                return info
            if self.connection.is_open is False:
                return info
            try:
                info = chip_command.get_product(self.connection)
            except pych9329.exceptions.InvalidStringEncoding:
                info = "Invalid string"
            except pych9329.exceptions.ChipBaseException:
                info = "Unknown error"
        return info

    # 恢复出厂设置
    def restore_factory_settings(self):
        with self.connection_mutex:
            if self.connection is None:
                return False
            if self.connection.is_open is False:
                return False
            chip_command.send_command_restore_factory_config(self.connection)

    # 复位芯片
    def reset_controller(self):
        with self.connection_mutex:
            if self.connection is None:
                return False
            if self.connection.is_open is False:
                return False
            chip_command.send_command_reset(self.connection)

    def mouse_send_data(
        self,
        button_name: str,
        x: int = 0,
        y: int = 0,
        wheel: int = 0,
        relative: bool = False,
    ):
        with self.connection_mutex:
            if self.connection is None:
                return False
            if self.connection.is_open is False:
                return False
            if relative is False:
                mouse.send_absolute_data(
                    self.connection,
                    x,
                    y,
                    button_name,
                    self.screen_x,
                    self.screen_y,
                    wheel,
                )
            else:
                mouse.send_relative_data(
                    self.connection, x, y, button_name, wheel
                )

    def convert_hid_key_code_to_ch9329_key(self, code: int) -> str:
        string_key: str = HexData.int_to_hex(code)
        ch9329_key: str | None = self.ch9329_hid_map.get(string_key, None)
        if ch9329_key is None:
            logger.error(f"hid key not found: {string_key}")
            ch9329_key = ""
        return ch9329_key

    def keyboard_send_data(self, keys: list, function_keys: list):
        with self.connection_mutex:
            if self.connection is None:
                return False
            if self.connection.is_open is False:
                return False
            if len(keys) > 6:
                keys = keys[0:6]
            if len(function_keys) > 8:
                function_keys = function_keys[0:8]
            keyboard.trigger(self.connection, keys, function_keys)
            # logger.debug(f"keyboard keys trigger : {keys}")
        return True

    # 获取键盘状态（指示灯状态）
    def keyboard_receive_status(self) -> tuple[int, dict[str, bool]]:
        status: bool = False
        reply_dict: dict = dict()
        with self.connection_mutex:
            if self.connection is None:
                return status, reply_dict
            if self.connection.is_open is False:
                return status, reply_dict
            # clear connection buffer
            # self.connection.readall()
            status, reply_dict = keyboard.receive_indicator_status(
                self.connection
            )

            logger.debug(f"receive keyboard indicator: {status}")
            if status:
                logger.debug(
                    f"keyboard usb connect: {reply_dict["usb_connect_status"]}"
                )
                logger.debug(f"num_lock: {reply_dict["num_lock"]}")
                logger.debug(f"caps_lock: {reply_dict["caps_lock"]}")
                logger.debug(f"scroll_lock: {reply_dict["scroll_lock"]}")
        return status, reply_dict

    def release(self, release_type: str = "all"):
        if self.connection is None:
            return
        if release_type == "mouse":
            mouse.release(self.connection)
        elif release_type == "keyboard":
            keyboard.release(self.connection)
        elif release_type == "all" or release_type == "any":
            mouse.release(self.connection)
            keyboard.release(self.connection)
        else:
            logger.debug(f"unknown release type: {release_type}")


class Controller(ControllerCh9329):
    pass


if __name__ == "__main__":
    pass
