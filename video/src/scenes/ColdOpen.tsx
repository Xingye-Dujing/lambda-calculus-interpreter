import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  LambdaGlyph,
  Reveal,
  Rule,
  SceneMeta,
  Stage,
} from '../components/core';

const concept = (n: string, zh: string, en: string) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
    <span
      style={{
        fontFamily: FONT_MONO,
        fontSize: 14,
        letterSpacing: '0.16em',
        color: C.faint,
      }}
    >
      {n}
    </span>
    <span style={{fontFamily: FONT_SERIF, fontSize: 36, color: C.text}}>{zh}</span>
    <span
      style={{
        fontFamily: FONT_LATIN,
        fontSize: 20,
        fontStyle: 'italic',
        color: C.faint,
      }}
    >
      {en}
    </span>
  </div>
);

export const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();

  const bodyOpacity = interpolate(frame, [470, 530], [1, 0], clamp);
  const titleOpacity = interpolate(frame, [520, 585], [0, 1], clamp);
  const titleY = interpolate(frame, [520, 585], [24, 0], clamp);

  return (
    <Stage>
      <SceneMeta chapter="A SMALLEST LANGUAGE" index="00" right="PROMO   2026" />

      <div style={{opacity: bodyOpacity}}>
        <div style={{position: 'absolute', left: 150, top: 260}}>
          <LambdaGlyph size={310} delay={4} duration={48} />
        </div>

        <div
          style={{
            position: 'absolute',
            left: 560,
            top: 272,
            width: 1,
            height: 330,
            background: C.border,
          }}
        />

        <div style={{position: 'absolute', left: 660, top: 260, width: 1050}}>
          <Kicker delay={18}>A LANGUAGE WITH ONLY THREE MOVES</Kicker>
          <div style={{height: 30}} />
          <Reveal delay={28} y={26}>
            <div
              style={{
                fontFamily: FONT_SERIF,
                fontSize: 88,
                lineHeight: 1.32,
                letterSpacing: '0.01em',
              }}
            >
              如果一门语言
              <br />
              只剩三个动作
            </div>
          </Reveal>
          <div style={{height: 40}} />
          <Reveal delay={135} y={14}>
            <div
              style={{
                fontFamily: FONT_SERIF,
                fontSize: 25,
                color: C.dim,
                lineHeight: 1.8,
              }}
            >
              没有循环 没有赋值 没有类型
              <br />
              它还能不能计算
            </div>
          </Reveal>
        </div>

        <div style={{position: 'absolute', left: 660, top: 760, width: 1110}}>
          <Rule delay={190} duration={40} color={C.border} />
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 40,
              paddingTop: 26,
            }}
          >
            <Reveal delay={210} y={14}>
              {concept('01', '变量', 'variable')}
            </Reveal>
            <Reveal delay={235} y={14}>
              {concept('02', '抽象', 'abstraction')}
            </Reveal>
            <Reveal delay={260} y={14}>
              {concept('03', '应用', 'application')}
            </Reveal>
          </div>
        </div>

        <div style={{position: 'absolute', left: 660, top: 520, width: 980}}>
          <Reveal delay={355} y={16}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'baseline',
                gap: 20,
                borderTop: `1px solid ${C.borderStrong}`,
                borderBottom: `1px solid ${C.border}`,
                padding: '18px 0',
                fontFamily: FONT_MONO,
                fontSize: 34,
                whiteSpace: 'nowrap',
              }}
            >
              <span>(λx. M) N</span>
              <span style={{color: C.faint}}>→</span>
              <span>M[x := N]</span>
              <span
                style={{
                  fontFamily: FONT_SERIF,
                  fontSize: 18,
                  color: C.faint,
                  letterSpacing: '0.06em',
                }}
              >
                β 归约  β-reduction
              </span>
            </div>
          </Reveal>
          <div style={{height: 22}} />
          <Reveal delay={410} y={12}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 27, color: C.dim}}>
              一条规则 重复使用
              <span style={{color: C.faint}}> 仅此而已</span>
            </div>
          </Reveal>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{textAlign: 'center'}}>
          <LambdaGlyph
            size={100}
            delay={520}
            duration={30}
            style={{margin: '0 auto 18px'}}
          />
          <div
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 92,
              letterSpacing: '0.06em',
              lineHeight: 1.2,
            }}
          >
            Lambda 演算解释器
          </div>
          <div
            style={{
              marginTop: 14,
              fontFamily: FONT_LATIN,
              fontSize: 28,
              letterSpacing: '0.16em',
              color: C.dim,
            }}
          >
            LAMBDA CALCULUS INTERPRETER
          </div>
          <div
            style={{
              marginTop: 38,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 18,
              fontFamily: FONT_SERIF,
              fontSize: 24,
              color: C.dim,
            }}
          >
            <span style={{width: 56, height: 1, background: C.borderStrong}} />
            一场可以看见过程的计算
            <span style={{width: 56, height: 1, background: C.borderStrong}} />
          </div>
        </div>
      </div>
    </Stage>
  );
};
