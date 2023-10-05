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
    UART_CMD_RESP               = uart_cmd(cmd = 0,     ret_data_len = 0)

    # Legacy cmd
    UART_CMD_SET_FREQ           = uart_cmd(cmd = 1,     ret_data_len = 0)
    UART_CMD_SAVE_NTH_FREQ      = uart_cmd(cmd = 2,     ret_data_len = 0)
    UART_CMD_GET_FREQ_COUNT     = uart_cmd(cmd = 3,     ret_data_len = 1)
    UART_CMD_GET_NTH_FREQ       = uart_cmd(cmd = 4,     ret_data_len = 4)
    UART_CMD_GET_ID             = uart_cmd(cmd = 5,     ret_data_len = 8,   recv_large_frame=True)
    UART_CMD_GET_HW_VER         = uart_cmd(cmd = 6,     ret_data_len = 1)
    UART_CMD_GET_FW_VER         = uart_cmd(cmd = 7,     ret_data_len = 3)
    UART_CMD_GET_POST_MULTI     = uart_cmd(cmd = 8,     ret_data_len = 1)
    UART_CMD_GET_REF_CLOCK      = uart_cmd(cmd = 9,     ret_data_len = 3)
    UART_CMD_GET_SN             = uart_cmd(cmd = 10,    ret_data_len = 23,  recv_large_frame=True)
    UART_CMD_GET_DIP_SW         = uart_cmd(cmd = 11,    ret_data_len = 1)

    # Extended cmd
    UART_CMD_SET_OUTPUT_POWER   = uart_cmd(cmd = 12,    ret_data_len = 0)
    UART_CMD_SET_OUTPUT_CONFIG  = uart_cmd(cmd = 13,    ret_data_len = 0)
    UART_CMD_SET_REF_CLOCK      = uart_cmd(cmd = 14,    ret_data_len = 0)
    UART_CMD_SET_REF_CONFIG     = uart_cmd(cmd = 15,    ret_data_len = 0)

    UART_CMD_GET_OUTPUT_POWER   = uart_cmd(cmd = 16,    ret_data_len = 1)
    UART_CMD_GET_OUTPUT_CONFIG  = uart_cmd(cmd = 17,    ret_data_len = 1)
    UART_CMD_GET_REF_CONFIG     = uart_cmd(cmd = 18,    ret_data_len = 1)
    UART_CMD_GET_FREQ           = uart_cmd(cmd = 19,    ret_data_len = 4)
    UART_CMD_GET_LOCK_STATUS    = uart_cmd(cmd = 20,    ret_data_len = 1)

class plo_return_code(Enum):
    PLO_RET_SUCCESS = 0
    PLO_RET_WARNING = auto()
    PLO_RET_ERROR_LRC= 0xfe
    PLO_RET_ERROR = 0xff

class return_code(Enum):
    RET_SUCCESS = 0

    RET_WARNING_FREQ = auto()

    RET_ERROR_OPEN_COM = auto()
    RET_ERROR_TIMEOUT = auto()
    RET_ERROR_SEND_LRC = auto()
    RET_ERROR_RECV_LRC = auto()
    RET_ERROR_NO_SAVED_FREQ = auto()
    RET_ERROR = auto()

class output_config(Enum):
    OUTA_OFF_OUTB_OFF = 0
    OUTA_ON_OUTB_OFF = auto()
    OUTA_OFF_OUTB_ON = auto()
    OUTA_ON_OUTB_ON = auto()

class ref_clock_config(Enum):
    REF_CLOCK_INTERNAL = 0
    REF_CLOCK_INTERNAL_OUT = auto()
    REF_CLOCK_EXTERNAL_IN = auto()


class plo_sg_api:
    version = '1.1.0'

    def __init__(self, com=None) -> None:
        # print('plo-sg-api version:', self.version)
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

        if len(self.dev_dict) == 0:
            print("no SG device found")

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

        # check lrc
        if ret_packet[-1] != self.__get_packet_lrc(ret_packet[:-1]):
            return return_code.RET_ERROR_RECV_LRC, ret_cmd, ret_payload

        if ret_packet[3] == plo_return_code.PLO_RET_ERROR_LRC.value:
            return return_code.RET_ERROR_SEND_LRC, ret_cmd, ret_payload

        ret_cmd = ret_packet[3]
        ret_payload = ret_packet[4:uart_cmd.ret_data_len + 4]
        if ret_cmd == plo_return_code.PLO_RET_ERROR.value:
            return return_code.RET_ERROR, ret_cmd, ret_payload

        return return_code.RET_SUCCESS, ret_cmd, ret_payload


    def set_freq_khz(self, freq:int, save_nth:int=None) -> return_code:
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
        # if ret_cmd == plo_return_code.PLO_RET_WARNING.value:
        #     ret_code = return_code.RET_WARNING_FREQ

        return ret_code

    def get_freq_khz(self, nth:int=None) -> Tuple[return_code, int]:
        uart_payload = self.__new_empty_payload()
        cmd = None

        if nth == None:
            cmd = uart_cmd_list.UART_CMD_GET_FREQ.value
        else:
            if nth < 0:
                return return_code.RET_ERROR, None
            cmd = uart_cmd_list.UART_CMD_GET_NTH_FREQ.value
            uart_payload[0] = nth

        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(cmd, uart_payload)

        if ret_code != return_code.RET_SUCCESS:
            return ret_code, None

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

    def get_reference_clock_khz(self) -> Tuple[return_code, int]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_REF_CLOCK.value)
        print(ret_code)
        ret = int.from_bytes(ret_payload, 'little')
        return ret_code, ret

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

    def set_output_power(self, power:int=12) -> return_code:
        uart_payload = self.__new_empty_payload()

        uart_payload[0] = power
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_SET_OUTPUT_POWER.value, uart_payload)
        return ret_code

    def get_output_power(self) -> Tuple[return_code, int]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_OUTPUT_POWER.value)

        if ret_code != return_code.RET_SUCCESS:
            return ret_code, None

        ret = int(ret_payload[0])
        return ret_code, ret

    def set_output_config(self, out_config:output_config=output_config.OUTA_ON_OUTB_ON) -> return_code:
        uart_payload = self.__new_empty_payload()

        uart_payload[0] = out_config.value
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_SET_OUTPUT_CONFIG.value, uart_payload)
        return ret_code

    def get_output_config(self) -> Tuple[return_code, output_config]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_OUTPUT_CONFIG.value)

        if ret_code != return_code.RET_SUCCESS:
            return ret_code, None

        ret = output_config(ret_payload[0])
        return ret_code, ret

    def set_ref_clock_config(self, ref_config:ref_clock_config=ref_clock_config.REF_CLOCK_INTERNAL) -> return_code:
        uart_payload = self.__new_empty_payload()

        uart_payload[0] = ref_config.value
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_SET_REF_CONFIG.value, uart_payload)
        return ret_code

    def get_ref_clock_config(self) -> Tuple[return_code, ref_clock_config]:
        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_REF_CONFIG.value)

        if ret_code != return_code.RET_SUCCESS:
            return ret_code, None

        ret = ref_clock_config(ret_payload[0])
        return ret_code, ret

    # def get_freq(self) -> Tuple[return_code, int]:
    #     uart_payload = self.__new_empty_payload()

    #     ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_FREQ.value, uart_payload)
    #     ret_freq = int.from_bytes(ret_payload[0:4], byteorder='little')

    #     return ret_code, ret_freq

    def get_lock_status(self) -> Tuple[return_code, int]:
        uart_payload = self.__new_empty_payload()

        ret_code, ret_cmd, ret_payload = self.__send_uart_packet(uart_cmd_list.UART_CMD_GET_LOCK_STATUS.value, uart_payload)

        if ret_code != return_code.RET_SUCCESS:
            return ret_code, None

        ret = ret_payload[0]

        return ret_code, ret


if __name__ == '__main__':

    argparser = argparse.ArgumentParser()
    argparser.add_argument("-v", "--version",       action='store_true',                help="plo_sg_api version")
    argparser.add_argument("-s", "--scan",          action='store_true',                help="Scan SG device and list info")
    argparser.add_argument("-c", "--com",           type=str,                           help="Com port. If not specified will connect to first SG in scan list")
    argparser.add_argument("-f", "--freq",          nargs='?', const=True,              help="Set/Get output frequency (kHz). Use --nth to access saved frequency")
    argparser.add_argument("-n", "--nth" ,          type=int,                           help="Nth saved frequency. Use with --freq")
    argparser.add_argument("-t", "--freq_cnt",      action='store_true',                help="Get how many set of frequency that can be saved")
    argparser.add_argument("--id",                  action='store_true',                help="Get internal PLO module id")
    argparser.add_argument("--hw_ver",              action='store_true',                help="Get internal PLO module hw version")
    argparser.add_argument("--fw_ver",              action='store_true',                help="Get internal PLO module fw version")
    argparser.add_argument("--post_multi",          action='store_true',                help="Get internal PLO output post multiplication. 0: X1, 1: X2, 2: X4")
    argparser.add_argument("--sn",                  action='store_true',                help="Get SG sn")
    argparser.add_argument("--plo_sn",              action='store_true',                help="Get internal PLO module internal sn")
    argparser.add_argument("--dip_sw",              action='store_true',                help="Get dip switch reading")
    argparser.add_argument("-p", "--out_pwr",       type=int, nargs='?', const=0xff,    help="Set/Get output power step (0 ~ 12)")
    argparser.add_argument("-o", "--out_cfg",       type=int, nargs='?', const=0xff,    help="Set/Get output config. 0: Disable OUT A&B, 1: Enable OUT A Only, 2: Enable OUT B Only, 3: Enable OUT A&B")
    argparser.add_argument("-k", "--ref_clk",       nargs='?', const=True,              help="Set/Get reference clock frequency (kHz)")
    argparser.add_argument("-r", "--ref_cfg",       type=int, nargs='?', const=0xff,    help="Set/Get reference clock config. 0: Internal ref clock, 1: Output ref clock, 2: External ref clock input")
    argparser.add_argument("-l", "--get_lock",      action='store_true',                help="Get lock status")

    args = argparser.parse_args()

    plo = plo_sg_api()

    # print version
    if args.version:
        print(plo.version)
        sys.exit(0)

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

    if args.freq != None:
        # no freq parameter => get freq
        if args.freq == True:
            if args.nth != None:    # nth parameter provided => get saved freq
                print(plo.get_freq_khz(args.nth))
            else:                   # no nth parameter provided => get current freq
                print(plo.get_freq_khz())
        # freq parameter provided => set freq
        elif args.freq.isdigit():
            freq = int(args.freq)
            if args.nth != None:    # nth parameter provided => set freq and save
                print(plo.set_freq_khz(freq, args.nth))
            else:                   # no nth parameter provided => set freq only
                print(plo.set_freq_khz(freq))
        else:
            print("Please enter valid arguments.")
            sys.exit(1)

    elif args.freq_cnt:
        print(plo.get_freq_count())

    elif args.id:
        print(plo.get_id())

    elif args.hw_ver:
        print(plo.get_hw_ver())

    elif args.fw_ver:
        print(plo.get_fw_ver())

    elif args.post_multi:
        print(plo.get_post_multiplier())

    elif args.ref_clk != None:
        # No parameter => get ref clk
        if args.ref_clk == True:
            print(plo.get_reference_clock_khz())
        # freq parameter provided => set ref clk
        elif args.ref_clk.isdigit():
            ref = int(args.ref_clk)
            print(plo.set_reference_clock_khz(ref))
        else:
            print("Please enter valid arguments.")
            sys.exit(1)

    elif args.sn:
        print(plo.get_sn())

    elif args.plo_sn:
        print(plo.get_plo_sn())

    elif args.dip_sw:
        print(plo.get_dip_switch())

    elif args.out_pwr != None and args.out_pwr < 0xff:
        print(plo.set_output_power(args.out_pwr))

    elif args.out_pwr == 0xff:
        print(plo.get_output_power())

    elif args.out_cfg != None and args.out_cfg < 0xff:
        print(plo.set_output_config(output_config(args.out_cfg)))
    elif args.out_cfg == 0xff:
        print(plo.get_output_config())

    elif args.ref_cfg != None and args.ref_cfg < 0xff:
        print(plo.set_ref_clock_config(ref_clock_config(args.ref_cfg)))
    elif args.ref_cfg == 0xff:
        print(plo.get_ref_clock_config())

    elif args.get_lock != None:
        print(plo.get_lock_status())

    else:
        print('please select a action.')
        sys.exit(1)

    sys.exit(0)