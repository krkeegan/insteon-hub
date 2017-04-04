from insteon.trigger import InsteonTrigger
from insteon.sequences.common import SetALDBDelta, BaseSequence, WriteALDBRecord


class ScanDeviceALDBi2(BaseSequence):
    '''Sequence object used for scanning the All link database of an i2
    device'''
    def start(self):
        self._device.aldb.clear_all_records()
        dev_bytes = {'msb': 0x00, 'lsb': 0x00}
        message = self._device.send_handler.create_message('read_aldb')
        message.insert_bytes_into_raw(dev_bytes)
        message.state_machine = 'query_aldb'
        self._device.queue_device_msg(message)
        # It would be nice to link the trigger to the msb and lsb, but we
        # don't technically have that yet at this point
        # pylint: disable=W0108
        trigger_attributes = {'msg_type': 'direct'}
        trigger = InsteonTrigger(device=self._device,
                                 command_name='read_aldb',
                                 attributes=trigger_attributes)
        trigger.trigger_function = lambda: self._i2_next_aldb()
        trigger.name = self._device.dev_addr_str + 'query_aldb'
        trigger.queue()

    def _i2_next_aldb(self):
        msb = self._device.last_rcvd_msg.get_byte_by_name('usr_3')
        lsb = self._device.last_rcvd_msg.get_byte_by_name('usr_4')
        aldb_key = self._device.aldb.get_aldb_key(msb, lsb)
        if self._device.aldb.get_record(aldb_key).is_last_aldb():
            self._device.remove_state_machine('query_aldb')
            self._device.aldb.print_records()
            aldb_sequence = SetALDBDelta(self._device)
            aldb_sequence.success_callback = lambda: self.on_success()
            aldb_sequence.failure_callback = lambda: self.on_failure()
            aldb_sequence.start()
        else:
            dev_bytes = self._device.aldb.get_next_aldb_address(msb, lsb)
            self._device.send_handler.i2_get_aldb(dev_bytes, 'query_aldb')
            trigger_attributes = {
                'usr_3': dev_bytes['msb'],
                'usr_4': dev_bytes['lsb'],
                'msg_type': 'direct'
            }
            # pylint: disable=W0108
            trigger = InsteonTrigger(device=self._device,
                                     command_name='read_aldb',
                                     attributes=trigger_attributes)
            trigger.trigger_function = lambda: self._i2_next_aldb()
            trigger.name = self._device.dev_addr_str + 'query_aldb'
            trigger.queue()


class WriteALDBRecordi2(WriteALDBRecord):
    def _perform_write(self):
        msg_attributes = self._compiled_record()
        trigger_attributes = {
            'cmd_2': 0x00,
            'msg_length': 'standard'
        }
        trigger = InsteonTrigger(device=self._device,
                                 command_name='write_aldb',
                                 attributes=trigger_attributes)
        aldb_sequence = SetALDBDelta(self._device)
        aldb_sequence.success_callback = lambda: self.on_success()
        aldb_sequence.failure_callback = lambda: self.on_failure()
        trigger.trigger_function = lambda: aldb_sequence.start()
        trigger.name = self._device.dev_addr_str + 'write_aldb'
        trigger.queue()
        msg = self._device.send_handler.create_message('write_aldb')
        msg.insert_bytes_into_raw(msg_attributes)
        self._device.queue_device_msg(msg)

    def _write_failure(self):
        self.on_failure
