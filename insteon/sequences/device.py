from insteon.trigger import Trigger


class ScanDeviceALDB(object):

    def __init__(self, device):
        self._device = device

    def start_query_aldb(self):
        self._device.aldb.clear_all_records()
        self.i1_start_aldb_entry_query(0x0F, 0xF8)

    def i1_start_aldb_entry_query(self, msb, lsb):
        # TODO do we need to add device ack as a field too? wouldn't a nack
        # cause this to trip?
        trigger_attributes = {
            'plm_cmd': 0x50,
            'from_addr_hi': self._device.dev_addr_hi,
            'from_addr_mid': self._device.dev_addr_mid,
            'from_addr_low': self._device.dev_addr_low,
            'cmd_1': 0x28,
            'cmd_2': msb
        }
        trigger = Trigger(trigger_attributes)
        trigger.trigger_function = lambda: self.send_peek_request(lsb)
        self._device.plm.trigger_mngr.add_trigger(self._device.dev_addr_str +
                                                  'query_aldb',
                                                  trigger)
        message = self._device.send_handler.create_message('set_address_msb')
        message.insert_bytes_into_raw({'msb': msb})
        message.state_machine = 'query_aldb'
        self._device.queue_device_msg(message)

    def peek_response(self):
        lsb = self._device.last_sent_msg.get_byte_by_name('cmd_2')
        msb_msg = self._device.search_last_sent_msg(
            insteon_cmd='set_address_msb')
        msb = msb_msg.get_byte_by_name('cmd_2')
        aldb_key = self._device.aldb.get_aldb_key(msb, lsb)
        if self._device.aldb.is_last_aldb(aldb_key):
            self._device.aldb.print_records()
            self._device.remove_state_machine('query_aldb')
            self._device.send_handler.set_aldb_delta()
        else:
            dev_bytes = self._device.aldb.get_next_aldb_address(msb, lsb)
            send_handler = self._device.send_handler
            if msb != dev_bytes['msb']:
                send_handler.i1_start_aldb_entry_query(dev_bytes['msb'],
                                                       dev_bytes['lsb'])
            else:
                self.send_peek_request(dev_bytes['lsb'])

    def send_peek_request(self, lsb):
        # TODO do we need to add device ack as a field too? wouldn't a nack
        # cause this to trip?
        trigger_attributes = {
            'plm_cmd': 0x50,
            'from_addr_hi': self._device.dev_addr_hi,
            'from_addr_mid': self._device.dev_addr_mid,
            'from_addr_low': self._device.dev_addr_low,
            'cmd_1': 0x2B
        }
        trigger = Trigger(trigger_attributes)
        trigger.trigger_function = lambda: self.peek_response()
        self._device.plm.trigger_mngr.add_trigger(self._device.dev_addr_str +
                                                  'query_aldb',
                                                  trigger)
        message = self._device.send_handler.create_message('peek_one_byte')
        message.insert_bytes_into_raw({'lsb': lsb})
        message.state_machine = 'query_aldb'
        self._device.queue_device_msg(message)
