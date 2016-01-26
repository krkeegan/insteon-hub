from insteon.plm_message import PLM_Message
from insteon.trigger import PLMTrigger
from insteon.sequences.i1_device import ScanDeviceALDBi1
from insteon.sequences.i2_device import ScanDeviceALDBi2
from insteon.sequences.common import StatusRequest


class GenericRcvdHandler(object):
    '''Provides the generic message handling that does not conflict with
    any Insteon devices.  Devices with distinct messages and needs should
    create their own message handler class that inherits and overrides the
    necessary elements'''
    def __init__(self, device):
        # Be careful storing any attributes, this object may be dropped
        # and replaced with a new object in a different class at runtime
        # if the dev_cat changes
        self._device = device
        self._last_rcvd_msg = None

    ###################################################
    #
    # attributes
    #
    ###################################################

    @property
    def last_rcvd_msg(self):
        return self._last_rcvd_msg

    @last_rcvd_msg.setter
    def last_rcvd_msg(self, msg):
        self._last_rcvd_msg = msg

    ###################################################
    #
    # Dispatchers
    #
    ###################################################

    def dispatch_msg_rcvd(self, msg):
        '''Selects the proper message path based on the message type.'''
        self.last_rcvd_msg = msg
        if msg.insteon_msg.message_type == 'direct':
            if not self._dispatch_direct(msg):
                print('unhandled direct message, perhaps dev_cat is wrong')
        elif msg.insteon_msg.message_type == 'direct_ack':
            self._process_direct_ack(msg)
        elif msg.insteon_msg.message_type == 'direct_nack':
            self._process_direct_nack(msg)
        elif msg.insteon_msg.message_type == 'broadcast':
            self._dispatch_broadcast(msg)
        elif msg.insteon_msg.message_type == 'alllink_cleanup_ack':
            self._process_alllink_cleanup(msg)

    def _dispatch_direct(self, msg):
        '''Dispatchs an incomming direct message to the correct function.
        Only extended messages are processed because the modem handles
        all standard direct messages.

        Returns
        True = a function successfully processed the message
        False = no function successfully processed the message'''
        ret = False
        if msg.insteon_msg.msg_length == 'extended':
            cmd_byte = msg.get_byte_by_name('cmd_1')
            if cmd_byte == 0x2F:
                ret = True
                self._ext_aldb_rcvd(msg)
        return ret

    def is_status_resp(self):
        '''Checks to see if the device is expecting a status response'''
        ret = False
        if (self._device.last_sent_msg.insteon_msg.device_cmd_name ==
                'light_status_request'):
            print('was status response')
            ret = True
        return ret

    def _process_direct_ack(self, msg):
        '''processes an incomming direct ack message, sets the
        allow_tigger flags and device_acks flags'''
        if self.is_status_resp():
            self._device.last_sent_msg.insteon_msg.device_ack = True
        elif not self._is_valid_direct_resp(msg):
            msg.allow_trigger = False
        elif self._dispatch_direct_ack(msg) is False:
            msg.allow_trigger = False
        else:
            self._device.last_sent_msg.insteon_msg.device_ack = True

    def _is_valid_direct_resp(self, msg):
        ret = True
        if (self._device.last_sent_msg.get_byte_by_name('cmd_1') !=
                msg.get_byte_by_name('cmd_1')):
            print('unexpected cmd_1 ignoring')
            ret = False
        elif self._device.last_sent_msg.plm_ack is not True:
            print('ignoring a device response received before PLM ack')
            ret = False
        elif self._device.last_sent_msg.insteon_msg.device_ack is not False:
            print('ignoring an unexpected device response')
            ret = False
        return ret

    def _dispatch_direct_ack(self, msg):
        '''processes an incomming direct ack message'''
        ret = False
        cmd_byte = msg.get_byte_by_name('cmd_1')
        if cmd_byte == 0X0D:
            version = msg.get_byte_by_name('cmd_2')
            self._device.set_engine_version(version)
            ret = True
        elif cmd_byte == 0x10:
            ret = self._common_prelim_ack(msg)
        elif cmd_byte == 0x28:
            ret = self._ack_set_msb(msg)
        elif cmd_byte == 0x2B:
            ret = True
            self._ack_peek_aldb(msg)
        elif cmd_byte == 0x2F:
            ret = self._ext_aldb_ack(msg)
        return ret

    def _process_direct_nack(self, msg):
        '''processes an incomming direct nack message'''
        if self._is_valid_direct_resp(msg):
            self._dispatch_direct_nack(msg)

    def _dispatch_direct_nack(self, msg):
        engine_version = self._device.attribute('engine_version')
        if (engine_version == 0x02 or engine_version is None):
            cmd_2 = msg.get_byte_by_name('cmd_2')
            if cmd_2 == 0xFF:
                print('nack received, senders ID not in database')
                self._device.attribute('engine_version', 0x02)
                self._device.last_sent_msg.insteon_msg.device_ack = True
                self._device.remove_state_machine(
                    self._device.last_sent_msg.state_machine)
                print('creating plm->device link')
                self._device.add_plm_to_dev_link()
            elif cmd_2 == 0xFE:
                print('nack received, no load')
                self._device.attribute('engine_version', 0x02)
                self._device.last_sent_msg.insteon_msg.device_ack = True
            elif cmd_2 == 0xFD:
                print('nack received, checksum is incorrect, resending')
                self._device.attribute('engine_version', 0x02)
                self._device.plm.wait_to_send = 1
                self._device._resend_msg(self._device.last_sent_msg)
            elif cmd_2 == 0xFC:
                print('nack received, Pre nack in case database search ',
                      'takes too long')
                self._device.attribute('engine_version', 0x02)
                self._device.last_sent_msg.insteon_msg.device_ack = True
            elif cmd_2 == 0xFB:
                print('nack received, illegal value in command')
                self._device.attribute('engine_version', 0x02)
                self._device.last_sent_msg.insteon_msg.device_ack = True
            else:
                print('device nack`ed the last command, no further ',
                      'details, resending')
                self._device.plm.wait_to_send = 1
                self._device._resend_msg(self._device.last_sent_msg)
        else:
            print('device nack`ed the last command, resending')
            self._device.plm.wait_to_send = 1
            self._device._resend_msg(self._device.last_sent_msg)

    def _dispatch_broadcast(self, msg):
        cmd_byte = msg.get_byte_by_name('cmd_1')
        if cmd_byte == 0X01:
            self._set_button_responder(msg)
        else:
            print('rcvd broadcast message of unknown type')

    def _process_alllink_cleanup(self,msg):
        # TODO is this actually received??  isn't the modem the only one who
        # get this message and doesn't it convert these to a special PLM Msg?
        # TODO set state of the device based on cmd acked
        # Clear queued cleanup messages if they exist
        self._device.remove_cleanup_msgs(msg)
        if (self._device.last_sent_msg and
                self._device.last_sent_msg.get_byte_by_name('cmd_1') ==
                msg.get_byte_by_name('cmd_1') and
                self._device.last_sent_msg.get_byte_by_name('cmd_2') ==
                msg.get_byte_by_name('cmd_2')):
            # Only set ack if this was sent by this device
            self._device.last_sent_msg.insteon_msg.device_ack = True

    ###################################################
    #
    # Message Processing Functions
    #
    ###################################################

    def _ext_aldb_ack(self, msg):
        # pylint: disable=W0613
        # msg is passed to all similar functions
        # TODO consider adding more time for following message to arrive
        last_sent_msg = self._device.last_sent_msg
        if (last_sent_msg.insteon_msg.device_prelim_ack is False and
                last_sent_msg.insteon_msg.device_ack is False):
            if self._device.last_sent_msg.get_byte_by_name('usr_2') == 0x00:
                # When reading ALDB a subsequent ext msg will contain record
                self._device.last_sent_msg.insteon_msg.device_prelim_ack = True
            else:
                self._device.last_sent_msg.insteon_msg.device_ack = True
        else:
            print('received spurious ext_aldb_ack')
        return False  # Never set ack

    def _ext_aldb_rcvd(self, msg):
        '''Sets the device_ack flag, while not specifically an ack'''
        last_sent_msg = self._device.last_sent_msg
        if (last_sent_msg.insteon_msg.device_prelim_ack is True and
                last_sent_msg.insteon_msg.device_ack is False):
            last_msg = self._device.search_last_sent_msg(
                insteon_cmd='read_aldb')
            req_msb = last_msg.get_byte_by_name('msb')
            req_lsb = last_msg.get_byte_by_name('lsb')
            msg_msb = msg.get_byte_by_name('usr_3')
            msg_lsb = msg.get_byte_by_name('usr_4')
            if ((req_lsb == msg_lsb and req_msb == msg_msb) or
                    (req_lsb == 0x00 and req_msb == 0x00)):
                aldb_entry = bytearray([
                    msg.get_byte_by_name('usr_6'),
                    msg.get_byte_by_name('usr_7'),
                    msg.get_byte_by_name('usr_8'),
                    msg.get_byte_by_name('usr_9'),
                    msg.get_byte_by_name('usr_10'),
                    msg.get_byte_by_name('usr_11'),
                    msg.get_byte_by_name('usr_12'),
                    msg.get_byte_by_name('usr_13')
                ])
                self._device.aldb.edit_record(self._device.aldb.get_aldb_key(
                                                                msg_msb,
                                                                msg_lsb),
                                              aldb_entry)
                self._device.last_sent_msg.insteon_msg.device_ack = True
        else:
            msg.allow_trigger = False
            print('received spurious ext_aldb record')

    def _ack_set_msb(self, msg):
        '''Returns true if the MSB Byte returned matches what we asked for'''
        if (self._device.last_sent_msg.get_byte_by_name('cmd_2') ==
                msg.get_byte_by_name('cmd_2')):
            ret = True
        else:
            ret = False
        return ret

    def _ack_peek_aldb(self, msg):
        '''Parses out the single ALDB byte and determines the MSB and LSB of the
        Byte.  Calls aldb function to store it'''
        lsb = self._device.last_sent_msg.get_byte_by_name('cmd_2')
        msb_msg = self._device.search_last_sent_msg(
            insteon_cmd='set_address_msb')
        msb = msb_msg.get_byte_by_name('cmd_2')
        byte = msg.get_byte_by_name('cmd_2')
        self._device.aldb.store_peeked_byte(msb, lsb, byte)
        return True  # Is there a scenario in which we return False?

    def _common_prelim_ack(self, msg):
        '''If prelim_ack and device_ack of last sent message are false, sets
        the prelim_ack, otherwise warns of spurious ack.  Always returns
        False'''
        # pylint: disable=W0613
        # msg is passed to all similar functions
        # TODO consider adding more time for following message to arrive
        last_sent_msg = self._device.last_sent_msg
        if (last_sent_msg.insteon_msg.device_prelim_ack is False and
                last_sent_msg.insteon_msg.device_ack is False):
            self._device.last_sent_msg.insteon_msg.device_prelim_ack = True
        else:
            print('received spurious device ack')
        return False  # Never set ack

    def _set_button_responder(self, msg):
        last_insteon_msg = self._device.last_sent_msg.insteon_msg
        if (last_insteon_msg.device_cmd_name == 'id_request' and
                last_insteon_msg.device_prelim_ack is True and
                last_insteon_msg.device_ack is False):
            dev_cat = msg.get_byte_by_name('to_addr_hi')
            sub_cat = msg.get_byte_by_name('to_addr_mid')
            firmware = msg.get_byte_by_name('to_addr_low')
            self._device.set_dev_version(dev_cat, sub_cat, firmware)
            last_insteon_msg.device_ack = True
            print('rcvd, broadcast updated devcat, subcat, and firmware')
        else:
            print('rcvd spurious set button pressed from device')


class GenericSendHandler(object):
    '''Provides the generic command handling that does not conflict with
    any Insteon devices.  Devices with distinct commands and needs should
    create their own message handler class that inherits and overrides the
    necessary elements'''
    def __init__(self, device):
        # Be careful storing any attributes, this object may be dropped
        # and replaced with a new object in a different class at runtime
        # if the dev_cat changes
        self._device = device
        self._last_sent_msg = None

    #################################################################
    #
    # Outgoing Message Construction
    #
    #################################################################

    def create_message(self, command_name):
        ret = None
        try:
            cmd_schema = self.msg_schema[command_name]
        except KeyError:
            print('command', command_name,
                  'not found for this device. Run DevCat?')
        else:
            command = cmd_schema.copy()
            command['name'] = command_name
            ret = PLM_Message(self._device.plm,
                              device=self._device,
                              plm_cmd='insteon_send',
                              dev_cmd=command)
        return ret

    def send_command(self, command_name, state=''):
        message = self.create_message(command_name)
        if message is not None:
            message.state_machine = state
            self._device.queue_device_msg(message)

    #################################################################
    #
    # Specific Outgoing messages
    #
    #################################################################

    def get_status(self, state_machine=''):
        status_sequence = StatusRequest(self._device)
        status_sequence.send_request()

    def get_engine_version(self, state_machine=''):
        self.send_command('get_engine_version', state_machine)

    def get_device_version(self, state_machine=''):
        self.send_command('id_request', state_machine)

    # Create PLM->Device Link
    #########################

    # TODO I think this should become a sequence too

    def add_plm_to_dev_link(self):
        # Put the PLM in Linking Mode
        # queues a message on the PLM
        message = self._device.plm.create_message('all_link_start')
        plm_bytes = {
            'link_code': 0x01,
            'group': 0x00,
        }
        message.insert_bytes_into_raw(plm_bytes)
        message.plm_success_callback = self._add_plm_to_dev_link_step2
        message.msg_failure_callback = self._add_plm_to_dev_link_fail
        message.state_machine = 'link plm->device'
        self._device.plm.queue_device_msg(message)

    def _add_plm_to_dev_link_step2(self):
        # Put Device in linking mode
        message = self.create_message('enter_link_mode')
        dev_bytes = {
            'cmd_2': 0x00
        }
        message.insert_bytes_into_raw(dev_bytes)
        message.insteon_msg.device_success_callback = (
            self._add_plm_to_dev_link_step3
        )
        message.msg_failure_callback = self._add_plm_to_dev_link_fail
        message.state_machine = 'link plm->device'
        self._device.queue_device_msg(message)

    def _add_plm_to_dev_link_step3(self):
        trigger_attributes = {
            'from_addr_hi': self._device.dev_addr_hi,
            'from_addr_mid': self._device.dev_addr_mid,
            'from_addr_low': self._device.dev_addr_low,
            'link_code': 0x01,
            'plm_cmd': 0x53
        }
        trigger = PLMTrigger(trigger_attributes)
        trigger.trigger_function = lambda: self._add_plm_to_dev_link_step4()
        self._device.plm.trigger_mngr.add_trigger(self._device.dev_addr_str +
                                                  'add_plm_step_3',
                                                  trigger)
        print('device in linking mode')

    def _add_plm_to_dev_link_step4(self):
        print('plm->device link created')
        self._device.plm.remove_state_machine('link plm->device')
        self._device.remove_state_machine('link plm->device')
        # Next init step
        self._device._init_step_2()

    def _add_plm_to_dev_link_fail(self):
        print('Error, unable to create plm->device link')
        self._device.plm.remove_state_machine('link plm->device')
        self._device.remove_state_machine('link plm->device')

    # ALDB commands
    ######################

    def query_aldb(self):
        if self._device.attribute('engine_version') == 0:
            scan_object = ScanDeviceALDBi1(self._device)
            scan_object.start_query_aldb()
        else:
            scan_obect = ScanDeviceALDBi2(self._device)
            scan_obect.start_query_aldb()

    def i2_get_aldb(self, dev_bytes, state_machine=''):
        message = self.create_message('read_aldb')
        message.insert_bytes_into_raw(dev_bytes)
        message.state_machine = state_machine
        self._device.queue_device_msg(message)

    def peek_aldb(self, lsb, state_machine=''):
        '''Sends a peek_one_byte command to the device for the lsb'''
        message = self.create_message('peek_one_byte')
        message.insert_bytes_into_raw({'lsb': lsb})
        message.state_machine = state_machine
        self._device.queue_device_msg(message)

    def create_responder(self, controller, d1, d2, d3):
                # Device Responder
                # D1 On Level D2 Ramp Rate D3 Group of responding device i1 00
                # i2 01
        pass

    def create_controller(self, responder):
                # Device controller
                # D1 03 Hops?? D2 00 D3 Group 01 of responding device??
        pass

    def _write_link(self, linked_obj, is_controller):
        if self._device.attribute('engine_version') == 2:
            pass  # run i2cs commands
        else:
            pass  # run i1 commands

    def write_aldb_record(self, msb, lsb, record):
        # TODO This is only the base structure still need to add more basically
        # just deletes things right now
        dev_bytes = {'msb': msb, 'lsb': lsb}
        msg = self.create_message('write_aldb')
        msg.insert_bytes_into_raw(dev_bytes)
        self._device.queue_device_msg(msg)

    #################################################################
    #
    # Message Schema
    #
    #################################################################

    @property
    def msg_schema(self):
        '''Returns a dictionary of all outgoing message types'''
        schema = {
            'product_data_request': {
                'cmd_1': {'default': 0x03},
                'cmd_2': {'default': 0x00},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'enter_link_mode': {
                'cmd_1': {'default': 0x09},
                'cmd_2': {'default': 0x00,
                          'name': 'group'},
                'usr_1': {'default': 0x00},
                'usr_2': {'default': 0x00},
                'usr_3': {'default': 0x00},
                'usr_4': {'default': 0x00},
                'usr_5': {'default': 0x00},
                'usr_6': {'default': 0x00},
                'usr_7': {'default': 0x00},
                'usr_8': {'default': 0x00},
                'usr_9': {'default': 0x00},
                'usr_10': {'default': 0x00},
                'usr_11': {'default': 0x00},
                'usr_12': {'default': 0x00},
                'usr_13': {'default': 0x00},
                'usr_14': {'default': 0x00},
                'msg_length': 'extended',
                'message_type': 'direct'
            },
            'get_engine_version': {
                'cmd_1': {'default': 0x0D},
                'cmd_2': {'default': 0x00},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'light_status_request': {
                'cmd_1': {'default': 0x19},
                'cmd_2': {'default': 0x00},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'id_request': {
                'cmd_1': {'default': 0x10},
                'cmd_2': {'default': 0x00},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'on': {
                'cmd_1': {'default': 0x11},
                'cmd_2': {'default': 0xFF},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'off': {
                'cmd_1': {'default': 0x13},
                'cmd_2': {'default': 0x00},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'set_address_msb': {
                'cmd_1': {'default': 0x28},
                'cmd_2': {'default': 0x00,
                          'name': 'msb'},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'peek_one_byte': {
                'cmd_1': {'default': 0x2B},
                'cmd_2': {'default': 0x00,
                          'name': 'lsb'},
                'msg_length': 'standard',
                'message_type': 'direct'
            },
            'read_aldb': {
                'cmd_1': {'default': 0x2F},
                'cmd_2': {'default': 0x00},
                'usr_1': {'default': 0x00},
                'usr_2': {'default': 0x00},
                'usr_3': {'default': 0x00,
                          'name': 'msb'},
                'usr_4': {'default': 0x00,
                          'name': 'lsb'},
                'usr_5': {'default': 0x01,
                          'name': 'num_records'},  # 0x00 = All,0x01 = 1 Record
                'usr_6': {'default': 0x00},
                'usr_7': {'default': 0x00},
                'usr_8': {'default': 0x00},
                'usr_9': {'default': 0x00},
                'usr_10': {'default': 0x00},
                'usr_11': {'default': 0x00},
                'usr_12': {'default': 0x00},
                'usr_13': {'default': 0x00},
                'usr_14': {'default': 0x00},
                'msg_length': 'extended',
                'message_type': 'direct'
            },
            'write_aldb': {
                'cmd_1': {'default': 0x2F},
                'cmd_2': {'default': 0x00},
                'usr_1': {'default': 0x00},
                'usr_2': {'default': 0x02},
                'usr_3': {'default': 0x00,
                          'name': 'msb'},
                'usr_4': {'default': 0x00,
                          'name': 'lsb'},
                'usr_5': {'default': 0x08,
                          'name': 'num_bytes'},
                'usr_6': {'default': 0x00,
                          'name': 'link_flags'},
                'usr_7': {'default': 0x00,
                          'name': 'group'},
                'usr_8': {'default': 0x00,
                          'name': 'dev_addr_hi'},
                'usr_9': {'default': 0x00,
                          'name': 'dev_addr_mid'},
                'usr_10': {'default': 0x00,
                           'name': 'dev_addr_low'},
                'usr_11': {'default': 0x00,
                           'name': 'data_1'},
                'usr_12': {'default': 0x00,
                           'name': 'data_2'},
                'usr_13': {'default': 0x00,
                           'name': 'data_3'},
                'usr_14': {'default': 0x00},
                'msg_length': 'extended',
                'message_type': 'direct'
            }
        }
        return schema