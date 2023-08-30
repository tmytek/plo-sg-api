import sys
import time
import argparse
from enum import Enum, auto
from typing import Tuple

import serial
from serial.tools import list_ports

"""
UART PACKET FORMAT

length is fixed to 18 bytes

| header | header | cmd len  | cmd   | payload | LRC   |
| 0xff   | 0xfe   | 0x10(16) | 1Byte | 13Bytes | 1Byte |

"""


class uart_cmd():
    def __init__(self, cmd, ret_data_len, recv_large_frame=False) -> None:
        self.cmd = cmd
        self.ret_data_len = ret_data_len
        self.recv_large_frame = recv_large_frame

class uart_cmd_list(Enum):
    UART_CMD_RESP           = uart_cmd(cmd = 0,     ret_data_len = 0)

    UART_CMD_SET_FREQ       = uart_cmd(cmd = 1,     ret_data_len = 0)
    UART_CMD_SAVE_NTH_FREQ  = uart_cmd(cmd = 2,     ret_data_len = 0)
    UART_CMD_GET_FREQ_COUNT = uart_cmd(cmd = 3,     ret_data_len = 1)
    UART_CMD_GET_NTH_FREQ   = uart_cmd(cmd = 4,     ret_data_len = 4)
    UART_CMD_GET_ID         = uart_cmd(cmd = 5,     ret_data_len = 8,   recv_large_frame=True)
    UART_CMD_GET_HW_VER     = uart_cmd(cmd = 6,     ret_data_len = 1)
    UART_CMD_GET_FW_VER     = uart_cmd(cmd = 7,     ret_data_len = 3)
    UART_CMD_GET_POST_MULTI = uart_cmd(cmd = 8,     ret_data_len = 1)
    UART_CMD_SET_REF_CLOCK  = uart_cmd(cmd = 9,     ret_data_len = 3)
    # UART_CMD_GET_REF_CLOCK  = uart_cmd(cmd = 10,    ret_data_len = 3)
    UART_CMD_GET_SN         = uart_cmd(cmd = 10,    ret_data_len = 23,  recv_large_frame=True)
    UART_CMD_GET_DIP_SW     = uart_cmd(cmd = 11,    ret_data_len = 1)

class return_code(Enum):
    RET_SUCCESS = 0

    RET_WARNING_FREQ = auto()

    RET_ERROR_OPEN_COM = auto()
    RET_ERROR_TIMEOUT = auto()
    RET_ERROR_SEND_LRC = auto()
    RET_ERROR_RECV_LRC = auto()
    RET_ERROR_NO_SAVED_FREQ = auto()
    RET_ERROR = auto()


class plo_sg_api:
    __version = '1.0.0'
    def __init__(self, com=None) -> None:
        print('plo-sg-api version:', self.__version)
        self.uart_header = [0xff, 0xfe]
        self.com = ''
        self.sn = ''
        self.dev_dict = {}

    def scan(self) -> dict:
        # scan serial port
        ports = list_ports.comports()
        dev = []

        for com_dev in sorted(ports):
            # print(com_dev.serial_number)
            if com_dev.serial_number != None and len(com_dev.serial_number) == 10 and com_dev.serial_number[0:2] == 'SG':
                sn = com_dev.serial_number[0:2] + '-' + com_dev.serial_number[2:]
                self.dev_dict[com_dev.device] = sn
                # print(self.dev_dict)
        return self.dev_dict

    def connect(self, com=None) -> return_code:
        # if no com port assigned then use the first one in scanned device list
        if com == None:
            if len(list(self.dev_dict)) > 0:
                com = list(self.dev_dict)[0]
            else:
                print('no com port selected')
                return return_code.RET_ERROR_OPEN_COM

        # open comport
        try:
            self.ser = serial.Serial(com, baudrate=9600, timeout=2)
        except Exception as e:
            print('open com error.', e)
            return return_code.RET_ERROR_OPEN_COM

        if com.upper()[0:3] == 'COM':
            com = com.upper()
        self.com = com
        if self.com in self.dev_dict:
            self.sn = self.dev_dict[com]
        print('device opened, com:', self.com + ', sn:', self.sn)
        return return_code.RET_SUCCESS

    def __get_packet_lrc(self, packet) -> int:
        mLRC = 0
        for packet_byte in packet[2:]:
            # print(packet_byte)
            mLRC += packet_byte
        return (4096 - mLRC) & 0xff

    def __new_empty_payload(self) -> bytes:
        # uart cmd packet is fix to 18 bytes long
        # payload exclude cmd header(2B), cmd len(1B), cmd(1B) and LRC(1B) => 18 - 2 - 1 - 1 - 1 = 13
        uart_packet = [0x00] * 13
        return uart_packet

    def __send_uart_packet(self, uart_cmd:uart_cmd, payload:bytes=None) -> Tuple[return_code, bytes, bytes]:
        '''
        Send packet
        '''
        uart_packet = []
        uart_packet.extend(self.uart_header)
        uart_packet.append(0x10)    # packet len
        uart_packet.append(uart_cmd.cmd)

        if payload == None:
            payload = self.__new_empty_payload()
        uart_packet.extend(payload)

        uart_packet.append(self.__get_packet_lrc(uart_packet))
        print('send:', list(map(hex, uart_packet)))

        self.ser.write(serial.to_bytes(uart_packet))
        time.sleep(0.5)

        '''
        Recv packet
        '''
        ret_cmd = None
        ret_payload = None
        ret_packet = None

        if uart_cmd.recv_large_frame == True:
            ret_packet_len = 28
        else:
            ret_packet_len = 10
        ret_packet = self.ser.read(ret_packet_len)

        # recv timeout
        if len(ret_packet) != ret_packet_len:
            return return_code.RET_ERROR_TIMEOUT, ret_cmd, ret_payload

        print('recv:', list(map(hex, ret_packet)))

        # # check lrc
        # if ret_packet[-1] != self.__get_packet_lrc(ret_packet[:-1]):
        #     return return_code.RET_ERROR_RECV_LRC, ret_cmd, ret_payload

        if ret_packet[3] == 0xfe:
            return return_code.RET_ERROR_SEND_LRC, ret_cmd, ret_payload

        ret_cmd = ret_packet[3]
        ret_payload = ret_packet[4:uart_cmd.ret_data_len + 4]
        return return_code.RET_SUCCESS, ret_cmd, ret_payload


    def set_freq(self, freq:int, save_nth:int=None) -> return_code:
        uart_payload = self.__new_empty_payload()
        cmd = None

        if save_nth == None:
            cmd = uart_cmd_list.UART_CMD_SET_FREQ.value
        else:
            cmd = uart_cmd_list.UART_CMD_SAVE_NTH_FREQ.value
            uart_payload[-1] = save_nth

        uart_payload[0] = freq & 0xff
        uart_payload[1] = (freq >> 8) & 0xff
        uart_payload[2] = (freq >> 16) & 0xff
        uart_payload[3] = (freq >> 24) & 0xff

        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(cmd, uart_payload)
        # print(ret_code, ret_cmd, ret_payload)

        # ignore WARNING_FREQ ret code (0x01)
        # if ret_cmd == 0x01:
        #     ret_code = return_code.RET_WARNING_FREQ

        return ret_code

    def get_freq(self, nth:int=0) -> Tuple[return_code, int]:
        uart_payload = self.__new_empty_payload()
        uart_payload[0] = nth

        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_NTH_FREQ.value, uart_payload)
        ret_freq = int.from_bytes(ret_payload[0:4], byteorder='little')
        if ret_cmd == 0xff:
            ret_code = return_code.RET_ERROR_NO_SAVED_FREQ
            ret_freq = None
        return ret_code, ret_freq

    def get_freq_count(self) -> Tuple[return_code, int]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_FREQ_COUNT.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = ret_payload[0]
        return ret_code, ret

    def get_id(self) -> Tuple[return_code, str]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_ID.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = ret_payload.decode('utf-8')
        return ret_code, ret

    def get_hw_ver(self) -> Tuple[return_code, str]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_HW_VER.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = str(hex(ret_payload[0]))

        return ret_code, ret

    def get_fw_ver(self) -> Tuple[return_code, str]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_FW_VER.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = str(ret_payload[0]) + '.' + str(ret_payload[1]) + '.' + str(ret_payload[2])
        return ret_code, ret

    def get_post_multiplier(self) -> Tuple[return_code, int]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_POST_MULTI.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            # convert ret value to post multiplication. 1 = x1, 2 = x2, 3 = x4
            ret = pow(2, ret_payload[0] - 1)
        return ret_code, ret

    def set_reference_clock_khz(self, ref_clk_khz) -> return_code:
        uart_payload = self.__new_empty_payload()
        uart_payload[0] = ref_clk_khz & 0xff
        uart_payload[1] = (ref_clk_khz >> 8) & 0xff
        uart_payload[2] = (ref_clk_khz >> 16) & 0xff
        uart_payload[3] = (ref_clk_khz >> 24) & 0xff

        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_SET_REF_CLOCK.value, uart_payload)
        return ret_code

    # def get_reference_clock_khz(self) -> Tuple[return_code, int]:
    #     ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_REF_CLOCK.value)
    #     print(ret_code)
    #     ret = int.from_bytes(ret_payload, 'big')
    #     return ret_code, ret

    def get_sn(self) -> str:
        return self.sn

    def get_plo_sn(self) -> Tuple[return_code, str]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_SN.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = ret_payload.decode('utf-8')
        return ret_code, ret

    def get_dip_switch(self) -> Tuple[return_code, int]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_DIP_SW.value)

        ret = None
        if ret_code == return_code.RET_SUCCESS:
            ret = ret_payload[0]

        return ret_code, ret


if __name__ == '__main__':

    argparser = argparse.ArgumentParser()
    argparser.add_argument("--scan",        action='store_true',    help="Scan SG device and list info")
    argparser.add_argument("--com",         type=str,               help="com port. If not specified will connect to first SG in scan list")
    argparser.add_argument("--set_freq",    type=int,               help="Set output frequency (kHz). Use --n to saved to eeprom")
    argparser.add_argument("--n",           type=int,               help="Nth saved frequency. Used with --set_freq")
    argparser.add_argument("--get_n_freq",  type=int,               help="Get Nth saved frequency (kHz)")
    argparser.add_argument("--freq_count",  action='store_true',    help="Get number of available saved frequency")
    argparser.add_argument("--id",          action='store_true',    help="Get PLO module id")
    argparser.add_argument("--hw_ver",      action='store_true',    help="Get PLO module hw version")
    argparser.add_argument("--fw_ver",      action='store_true',    help="Get PLO module fw version")
    argparser.add_argument("--post_multi",  action='store_true',    help="Get PLO output post multiplication. X1, X2 or X4")
    argparser.add_argument("--set_ref",     type=int,               help="Set reference clock frequency (kHz)")
    argparser.add_argument("--sn",          action='store_true',    help="Get SG sn")
    argparser.add_argument("--plo_sn",      action='store_true',    help="Get PLO module internal sn")
    argparser.add_argument("--dip_sw",      action='store_true',    help="Get dip switch reading")

    args = argparser.parse_args()
    # argparser.print_help()

    plo = plo_sg_api()
    scanned_dev = plo.scan()

    if args.scan:
        print(scanned_dev)
        sys.exit(0)

    if args.com == None:
        ret = plo.connect()
    else:
        ret = plo.connect(args.com)
    if ret != return_code.RET_SUCCESS:
        sys.exit(1)

    if args.set_freq != None:
        print(plo.set_freq(args.set_freq, args.n))
    elif args.get_n_freq != None:
        print(plo.get_freq(args.get_n_freq))
    elif args.freq_count:
        print(plo.get_freq_count())
    elif args.id:
        print(plo.get_id())
    elif args.hw_ver:
        print(plo.get_hw_ver())
    elif args.fw_ver:
        print(plo.get_fw_ver())
    elif args.post_multi:
        print(plo.get_post_multiplier())
    elif args.set_ref != None:
        print(plo.set_reference_clock_khz(args.set_ref))
    elif args.sn:
        print(plo.get_sn())
    elif args.plo_sn:
        print(plo.get_plo_sn())
    elif args.dip_sw:
        print(plo.get_dip_switch())
    else:
        print('please select a action.')
        sys.exit(0)