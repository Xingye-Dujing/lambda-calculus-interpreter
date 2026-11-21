import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';
import {FontFaces} from './ui';

export type Profile = 'bili' | 'douyin';

export type Caption = {
  zh: string;
};

export type FootageProps = {
  profile: Profile;
  scene: string;
  chapter: string;
  no: string;
  caption: Caption[];
};

/** 真实浏览器录屏 + 双语字幕 / real browser footage with bilingual subtitles */
export const Footage: React.FC<FootageProps> = ({
  profile,
  scene,
  chapter,
  no,
  caption,
}) => {
  const frame = useCurrentFrame();
  const vertical = profile === 'douyin';

  const enter = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const leave = interpolate(frame, [22, 34], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const kickerOpacity = enter * leave;

  const padX = vertical ? 56 : 92;
  const captionBottom = vertical ? 300 : 74;

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />
      <OffthreadVideo
        src={staticFile(`real/${profile}/clip-${scene}.mp4`)}
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />

      {/* 字幕区的浅色衬底，让字压在录屏上也清楚 / paper scrim for legibility */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: vertical ? 620 : 260,
          background: `linear-gradient(to top, ${C.bg} 0%, rgba(250,250,248,0.94) 42%, rgba(250,250,248,0) 100%)`,
          pointerEvents: 'none',
        }}
      />
      {vertical ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 0,
            height: 180,
            background: `linear-gradient(to bottom, ${C.bg} 0%, rgba(250,250,248,0) 100%)`,
            pointerEvents: 'none',
          }}
        />
      ) : null}

      {/* 横屏才显示章节标签；竖屏让录屏自己说话 / kicker only on landscape */}
      {vertical ? null : (
        <div
          style={{
            position: 'absolute',
            top: 34,
            left: padX,
            display: 'flex',
            alignItems: 'baseline',
            gap: 20,
            opacity: kickerOpacity,
            fontFamily: FONT_MONO,
            fontSize: 17,
            letterSpacing: '0.18em',
            color: C.dim,
          }}
        >
          <span style={{color: C.faint}}>{no}</span>
          <span>{chapter}</span>
        </div>
      )}

      {/* 字幕 / subtitles */}
      <div
        style={{
          position: 'absolute',
          left: padX,
          right: padX,
          bottom: captionBottom,
          display: 'flex',
          flexDirection: 'column',
          gap: vertical ? 14 : 10,
        }}
      >
        {caption.map((line, i) => {
          const appear = interpolate(
            frame,
            [i * 11, i * 11 + 14],
            [0, 1],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
          );
          return (
            <div
              key={i}
              style={{
                opacity: appear,
                transform: `translateY(${(1 - appear) * 12}px)`,
                fontFamily: i === 0 ? FONT_SERIF : FONT_MONO,
                fontSize: vertical ? (i === 0 ? 62 : 30) : (i === 0 ? 52 : 24),
                lineHeight: 1.32,
                color: i === 0 ? C.text : C.dim,
                whiteSpace: 'pre-line',
                textShadow: `0 1px 0 ${C.bg}`,
              }}
            >
              {line.zh}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
