import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  Label,
  LambdaGlyph,
  Reveal,
  Rule,
  SceneMeta,
  Stage,
} from '../components/core';

const audience = (index: string, title: string, en: string, body: React.ReactNode) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 14,
        borderBottom: `1px solid ${C.border}`,
        paddingBottom: 12,
      }}
    >
      <span
        style={{
          fontFamily: FONT_MONO,
          fontSize: 14,
          color: C.faint,
          letterSpacing: '0.12em',
        }}
      >
        {index}
      </span>
      <span style={{fontFamily: FONT_SERIF, fontSize: 32}}>{title}</span>
      <span style={{flex: 1}} />
      <span
        style={{
          fontFamily: FONT_LATIN,
          fontSize: 17,
          fontStyle: 'italic',
          color: C.faint,
        }}
      >
        {en}
      </span>
    </div>
    <div style={{fontFamily: FONT_SERIF, fontSize: 21, lineHeight: 1.7, color: C.dim}}>
      {body}
    </div>
  </div>
);

export const Positioning: React.FC = () => {
  const frame = useCurrentFrame();
  const exact = interpolate(frame, [560, 630], [0, 1], clamp);
  const cards = interpolate(frame, [360, 430], [0, 1], clamp);

  return (
    <Stage>
      <SceneMeta chapter="POSITIONING" index="03" />

      <div style={{position: 'absolute', left: 120, top: 170, width: 1160}}>
        <Kicker delay={6}>POSITIONING   项目定位</Kicker>
        <div style={{height: 34}} />
        <Reveal delay={20} y={22}>
          <div style={{fontFamily: FONT_SERIF, fontSize: 86, lineHeight: 1.36}}>
            这不是一台
            <br />
            替你做题的计算器
          </div>
        </Reveal>
        <div style={{height: 32}} />
        <Reveal delay={110} y={18}>
          <div
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 50,
              lineHeight: 1.5,
              color: C.dim,
            }}
          >
            它是一台显微镜
            <br />
            <span style={{color: C.text}}>把归约的过程放大给你看</span>
          </div>
        </Reveal>
      </div>

      <div style={{position: 'absolute', right: 150, top: 190}}>
        <LambdaGlyph size={220} delay={10} duration={38} />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          right: 120,
          top: 690,
          opacity: cards,
        }}
      >
        <Rule delay={380} duration={34} color={C.border} />
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 58,
            paddingTop: 28,
          }}
        >
          {audience(
            '01',
            '学习者',
            'learner',
            <>
              从一条 β 规则出发 慢慢走到 Y 组合子
              <br />
              把为什么留在屏幕上 而不是只留下答案
            </>,
          )}
          {audience(
            '02',
            '教师',
            'teacher',
            <>
              把归约路径 求值策略 语法树投到课堂上
              <br />
              同一道题 可以讲出不同的路
            </>,
          )}
          {audience(
            '03',
            '好奇者',
            'curious',
            <>
              亲手拆开计算这个词
              <br />
              不需要先学完一门语言 才能开始提问
            </>,
          )}
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          bottom: 92,
          right: 120,
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          opacity: exact,
        }}
      >
        <div
          style={{
            fontFamily: FONT_SERIF,
            fontSize: 28,
            color: C.dim,
          }}
        >
          为理解而做 不为炫技而做
        </div>
        <Label color={C.faint}>A MICROSCOPE FOR REDUCTION</Label>
      </div>
    </Stage>
  );
};
