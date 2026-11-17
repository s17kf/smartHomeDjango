from django.conf import settings
from django.test import SimpleTestCase, override_settings

from .. import mqtt
from ..models import Device


class TopicsTests(SimpleTestCase):
    """Tematy `home/<slug>/…` i payload `config` (`specs/topics.md`, `specs/payloads.md`)."""

    def test_parse_topic(self):
        self.assertEqual(mqtt.parse_topic('home/plug-1/state'), ('plug-1', 'state'))
        self.assertEqual(mqtt.parse_topic('home/temp-salon/telemetry'), ('temp-salon', 'telemetry'))
        for topic in ('home/Plug-1/state', 'home/plug_1/state', 'home/plug-1', 'home/plug-1/state/x',
                      'gateway/status', 'shelly/plug1/online', f'home/{"x" * 51}/state', 'home//state'):
            with self.subTest(topic=topic):
                self.assertIsNone(mqtt.parse_topic(topic))

    def test_config_message(self):
        device = Device(slug='plug-1', kind='switch', driver='shelly',
                        params={'prefix': 'shelly/plug1', 'component': 'switch:0', 'opis': 'żółć'})
        self.assertEqual(mqtt.config_messages(device), [mqtt.Message(
            'home/plug-1/config',
            '{"kind":"switch","driver":"shelly","params":{"prefix":"shelly/plug1","component":"switch:0",'
            '"opis":"żółć"}}'.encode(),
            retain=True,
        )])

    def test_removal_messages(self):
        # najpierw `config` – gateway zatrzymuje adapter, potem tematy stanu
        self.assertEqual(mqtt.removal_messages('plug-1'), [
            mqtt.Message(f'home/plug-1/{name}', b'', retain=True)
            for name in ('config', 'state', 'telemetry', 'availability')
        ])


class MemoryBrokerTests(SimpleTestCase):
    def setUp(self):
        self.broker = mqtt.MemoryBroker()

    def test_retained(self):
        self.broker.publish([mqtt.Message('home/a/config', b'1', True), mqtt.Message('home/b/config', b'2', True),
                             mqtt.Message('home/a/set', b'{}', False), mqtt.Message('home/a/state', b'3', True)])
        self.assertEqual(self.broker.retained('home/+/config'), {'home/a/config': b'1', 'home/b/config': b'2'})
        self.broker.publish([mqtt.Message('home/a/config', b'', True)])
        self.assertEqual(self.broker.retained('home/+/config'), {'home/b/config': b'2'})
        self.assertEqual(len(self.broker.published), 5)

    def test_error(self):
        self.broker.error = 'connection refused'
        with self.assertRaises(mqtt.MqttError):
            self.broker.publish([mqtt.Message('home/a/config', b'1', True)])
        with self.assertRaises(mqtt.MqttError):
            self.broker.retained('home/+/config')
        self.assertEqual(self.broker.published, [])

    def test_tests_use_memory_broker(self):
        # runner testów podmienia broker – testy nie łączą się z prawdziwym
        self.assertEqual(settings.MQTT_BROKER, 'devices.mqtt.MemoryBroker')
        self.assertIsInstance(mqtt.broker(), mqtt.MemoryBroker)


class MqttBrokerTests(SimpleTestCase):
    """Prawdziwy broker – tylko błędy przed wymianą pakietów MQTT (bez brokera w testach)."""

    MESSAGE = [mqtt.Message('home/a/config', b'1', True)]

    @override_settings(MQTT_PASSWORD='')
    def test_no_password(self):
        with self.assertRaisesMessage(mqtt.MqttError, 'MQTT_BACKEND_PASSWORD'):
            mqtt.MqttBroker().publish(self.MESSAGE)

    @override_settings(MQTT_HOST='127.0.0.1', MQTT_PORT=1, MQTT_PASSWORD='x')
    def test_connection_refused(self):
        with self.assertRaisesMessage(mqtt.MqttError, 'cannot connect to 127.0.0.1:1'):
            mqtt.MqttBroker().publish(self.MESSAGE)

    def test_nothing_to_publish(self):
        mqtt.MqttBroker().publish([])
