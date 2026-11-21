import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';
import {FontFaces} from './ui';
import type {Profile} from './Footage';

const LAMBDA_WATERMARK =
  'M22 12c8-8 16-8 24 0M22 20c8 8 16 8 24 0M46 4 34 28';

export type ChapterCardProps = {
  profile: Profile;
  no: string;
  kicker: string;
  title: string;
  formula?: string;
  body?: string;
};

/** 概念转场卡：纯纸面，让录屏段落之间有一次干净的停顿 */
export const ChapterCard: React.FC<ChapterCardProps> = ({
  profile,
  no,
  kicker,
  title,
  formula,
  body,
}) => {
  const frame = useCurrentFrame();
  const vertical = profile === 'douyin';

  const rise = (delay: number) =>
    interpolate(frame, [delay, delay + 18], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });

  const padX = vertical ? 72 : 150;
  const titleSize = vertical ? 74 : 98;

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />

      {/* 淡淡的 λ 水印，纸面保持干净 / a faint λ watermark, nothing else */}
      <svg
        viewBox="0 0 68 32"
        style={{
          position: 'absolute',
          right: padX,
          top: vertical ? 210 : 72,
          width: vertical ? 120 : 96,
          opacity: 0.16,
        }}
      >
        <path
          d={LAMBDA_WATERMARK}
          fill="none"
          stroke={C.text}
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      </svg>

      <div
        style={{
          position: 'absolute',
          top: vertical ? 214 : 74,
          left: padX,
          right: padX,
          display: 'flex',
          alignItems: 'baseline',
          gap: vertical ? 18 : 26,
          opacity: rise(2),
          fontFamily: FONT_MONO,
          fontSize: vertical ? 25 : 18,
          letterSpacing: '0.2em',
          color: C.dim,
        }}
      >
        <span style={{color: C.faint}}>{no}</span>
        <span>{kicker}</span>
      </div>

      <div
        style={{
          position: 'absolute',
          top: vertical ? 360 : 248,
          left: padX,
          right: padX,
          opacity: rise(8),
          transform: `translateY(${(1 - rise(8)) * 20}px)`,
          fontFamily: FONT_SERIF,
          fontSize: titleSize,
          lineHeight: 1.36,
          color: C.text,
          whiteSpace: 'pre-line',
        }}
      >
        {title}
      </div>

      {formula ? (
        <div
          style={{
            position: 'absolute',
            top: vertical ? 760 : 542,
            left: padX,
            right: padX,
            opacity: rise(18),
            padding: vertical ? '26px 28px' : '22px 30px',
            border: `1px solid ${C.borderStrong}`,
            background: 'rgba(255,255,255,0.66)',
            fontFamily: FONT_MONO,
            fontSize: vertical ? 36 : 38,
            color: C.text,
            letterSpacing: '0.01em',
          }}
        >
          {formula}
        </div>
      ) : null}

      {body ? (
        <div
          style={{
            position: 'absolute',
            left: padX,
            right: padX,
            bottom: vertical ? 330 : 96,
            opacity: rise(formula ? 28 : 20),
            fontFamily: FONT_SERIF,
            fontSize: vertical ? 40 : 30,
            lineHeight: 1.72,
            color: C.dim,
            whiteSpace: 'pre-line',
          }}
        >
          {body}
        </div>
      ) : null}

      <div
        style={{
          position: 'absolute',
          left: padX,
          right: padX,
          bottom: vertical ? 252 : 56,
          height: 1,
          background: C.border,
          opacity: 0.8,
        }}
      />
    </AbsoluteFill>
  );
};
