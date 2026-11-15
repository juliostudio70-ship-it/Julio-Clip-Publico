from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reframe import FacePath, SpeakerFocus


class SpeakerFocusTest(unittest.TestCase):
    def test_turns_change_with_audio_and_hold_in_silence_or_a_tie(self):
        left, right = (.25, .5, 25), (.75, .5, 10)
        speakers, path = SpeakerFocus(), FacePath()
        centers = []

        # Muestras de movimiento ya compensado, con turnos, empate y silencio.
        with patch('reframe.mouth_motion', side_effect=lambda _previous, current, _np: current):
            # Dos segundos por turno: el desplazamiento nuevo está limitado a .08 por muestra.
            phases = [(16, (8, 0), 1), (16, (0, 8), 1), (16, (8, 0), 0),
                      (16, (7, 7), 1), (16, (8, 0), 1)]
            index = 0
            for count, movement, voice in phases:
                for _ in range(count):
                    # El detector puede devolver las mismas dos caras en distinto orden.
                    boxes, patches = [left, right], list(movement)
                    if index % 2:
                        boxes.reverse()
                        patches.reverse()
                    speaker = speakers.update(index, boxes, patches, voice, None)
                    center = path.update(boxes, speaker=speaker)
                    index += 1
                centers.append(center[0])
        self.assertLess(centers[0], .30)
        self.assertGreater(centers[1], .68)
        self.assertGreater(centers[2], .68)
        self.assertGreater(centers[3], .68)
        self.assertLess(centers[4], .32)

    def test_one_face_follows_without_a_speaker_signal(self):
        path = FacePath()
        self.assertEqual(path.update([(.35, .5, 12)]), (.35, .5))
        self.assertGreater(path.update([(.50, .5, 12)])[0], .40)

    def test_switch_is_rate_limited_and_close_faces_share_the_frame(self):
        path = FacePath()
        path.update([(.2, .5, 10)])
        previous = path.center
        for _ in range(12):
            center = path.update([(.8, .5, 10)], speaker=(.8, .5, 10))
            self.assertLessEqual(abs(center[0]-previous[0]), .080001)
            previous = center
        self.assertGreater(center[0], .75)
        group = FacePath(crop_fraction=.4)
        center = group.update([(.42, .5, 10, .07, .1), (.58, .5, 9, .07, .1)])
        self.assertAlmostEqual(center[0], .5)
