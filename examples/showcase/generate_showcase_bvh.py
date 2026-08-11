"""Generate the original synthetic BVH used by the public Shogun showcase."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

FRAME_COUNT = 240
FRAME_TIME = 1.0 / 30.0

HIERARCHY = """HIERARCHY
ROOT Hips
{
  OFFSET 0.000000 98.000000 0.000000
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT Spine
  {
    OFFSET 0.000000 12.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT Chest
    {
      OFFSET 0.000000 15.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT Neck
      {
        OFFSET 0.000000 13.000000 0.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT Head
        {
          OFFSET 0.000000 9.000000 0.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.000000 8.000000 0.000000
          }
        }
      }
      JOINT LeftShoulder
      {
        OFFSET 6.000000 11.000000 0.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT LeftArm
        {
          OFFSET 12.000000 0.000000 0.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          JOINT LeftForeArm
          {
            OFFSET 14.000000 0.000000 0.000000
            CHANNELS 3 Zrotation Xrotation Yrotation
            JOINT LeftHand
            {
              OFFSET 11.000000 0.000000 0.000000
              CHANNELS 3 Zrotation Xrotation Yrotation
              End Site
              {
                OFFSET 5.000000 0.000000 0.000000
              }
            }
          }
        }
      }
      JOINT RightShoulder
      {
        OFFSET -6.000000 11.000000 0.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightArm
        {
          OFFSET -12.000000 0.000000 0.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          JOINT RightForeArm
          {
            OFFSET -14.000000 0.000000 0.000000
            CHANNELS 3 Zrotation Xrotation Yrotation
            JOINT RightHand
            {
              OFFSET -11.000000 0.000000 0.000000
              CHANNELS 3 Zrotation Xrotation Yrotation
              End Site
              {
                OFFSET -5.000000 0.000000 0.000000
              }
            }
          }
        }
      }
    }
  }
  JOINT LeftUpLeg
  {
    OFFSET 7.000000 -9.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT LeftLeg
    {
      OFFSET 0.000000 -36.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT LeftFoot
      {
        OFFSET 0.000000 -35.000000 2.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT LeftToe
        {
          OFFSET 0.000000 -5.000000 13.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.000000 0.000000 7.000000
          }
        }
      }
    }
  }
  JOINT RightUpLeg
  {
    OFFSET -7.000000 -9.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT RightLeg
    {
      OFFSET 0.000000 -36.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT RightFoot
      {
        OFFSET 0.000000 -35.000000 2.000000
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightToe
        {
          OFFSET 0.000000 -5.000000 13.000000
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {
            OFFSET 0.000000 0.000000 7.000000
          }
        }
      }
    }
  }
}
"""


def _triple(z: float = 0.0, x: float = 0.0, y: float = 0.0) -> list[float]:
    return [z, x, y]


def frame_values(frame: int) -> list[float]:
    phase = 2.0 * math.pi * frame / 60.0
    phrase = 2.0 * math.pi * frame / FRAME_COUNT
    left = math.sin(phase)
    right = math.sin(phase + math.pi)
    turn = 18.0 * math.sin(phrase)
    accent = math.sin(phase * 0.5) ** 3

    values = [
        18.0 * math.sin(phrase),
        2.5 * abs(math.sin(phase * 2.0)),
        35.0 * math.sin(phrase * 0.5),
        4.0 * math.sin(phase),
        2.0 * math.sin(phase * 2.0),
        turn,
    ]
    values += _triple(5.0 * math.sin(phase), 7.0 * accent, 8.0 * math.sin(phrase * 2.0))
    values += _triple(-4.0 * math.sin(phase), 5.0 * accent, -12.0 * math.sin(phrase * 2.0))
    values += _triple(2.0 * math.sin(phase * 0.5), -5.0 * accent, 8.0 * math.sin(phrase))
    values += _triple(-3.0 * math.sin(phase), 3.0 * math.sin(phase * 0.5), -turn * 0.35)

    values += _triple(8.0, 0.0, -12.0)
    values += _triple(28.0 + 18.0 * accent, 42.0 * left, 8.0 * math.sin(phrase * 2.0))
    values += _triple(-18.0 - 42.0 * max(0.0, left), 10.0 * left, 0.0)
    values += _triple(8.0 * math.sin(phase * 2.0), 4.0 * left, 12.0 * accent)

    values += _triple(-8.0, 0.0, 12.0)
    values += _triple(-28.0 - 18.0 * accent, 42.0 * right, -8.0 * math.sin(phrase * 2.0))
    values += _triple(18.0 + 42.0 * max(0.0, right), 10.0 * right, 0.0)
    values += _triple(-8.0 * math.sin(phase * 2.0), 4.0 * right, -12.0 * accent)

    values += _triple(2.0 * left, 32.0 * left, -5.0 * turn)
    values += _triple(0.0, 8.0 + 48.0 * max(0.0, -left), 0.0)
    values += _triple(0.0, -10.0 - 20.0 * max(0.0, left), 2.0 * left)
    values += _triple(0.0, 8.0 * max(0.0, left), 0.0)

    values += _triple(2.0 * right, 32.0 * right, 5.0 * turn)
    values += _triple(0.0, 8.0 + 48.0 * max(0.0, -right), 0.0)
    values += _triple(0.0, -10.0 - 20.0 * max(0.0, right), 2.0 * right)
    values += _triple(0.0, 8.0 * max(0.0, right), 0.0)

    if len(values) != 66:
        raise AssertionError(f"expected 66 BVH channels, got {len(values)}")
    return values


def generate(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [HIERARCHY, "MOTION", f"Frames: {FRAME_COUNT}", f"Frame Time: {FRAME_TIME:.7f}"]
    lines.extend(
        " ".join(f"{value:.6f}" for value in frame_values(frame)) for frame in range(FRAME_COUNT)
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "assets" / "dcc-mcp-shogun-showcase.bvh",
    )
    args = parser.parse_args()
    generate(args.output.resolve())
    print(args.output.name)


if __name__ == "__main__":
    main()
