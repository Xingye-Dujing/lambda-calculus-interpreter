import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  CodeLine,
  Kicker,
  Label,
  Reveal,
  Rule,
  SceneMeta,
  Stage,
} from '../components/core';

const GramLine: React.FC<{
  delay: number;
  lhs: string;
  arrow: string;
  rhs: React.ReactNode;
  note: string;
  active?: boolean;
}> = ({delay, lhs, arrow, rhs, note, active = false}) => (
  <Reveal delay={delay} y={14} duration={20}>
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '90px 50px 1fr 230px',
        alignItems: 'baseline',
        padding: '14px 0',
        borderBottom: `1px solid ${active ? C.borderStrong : C.border}`,
      }}
    >
      <span
        style={{
          fontFamily: FONT_MONO,
          fontSize: 36,
          color: C.text,
          letterSpacing: '0.02em',
        }}
      >
        {lhs}
      </span>
      <span style={{fontFamily: FONT_MONO, fontSize: 30, color: C.faint}}>
        {arrow}
      </span>
      <span
        style={{
          fontFamily: FONT_MONO,
          fontSize: 36,
          color: C.text,
          whiteSpace: 'pre',
        }}
      >
        {rhs}
      </span>
      <span
        style={{
          fontFamily: FONT_SERIF,
          fontSize: 22,
          color: C.faint,
          textAlign: 'right',
        }}
      >
        {note}
      </span>
    </div>
  </Reveal>
);

export const OneRule: React.FC = () => {
  const frame = useCurrentFrame();

  const substitutionHighlight = interpolate(
    frame,
    [610, 650, 780, 820],
    [0, 1, 1, 0],
    clamp,
  );
  const bodyFade = interpolate(frame, [1110, 1180], [1, 0], clamp);
  const endFade = interpolate(frame, [1150, 1220], [0, 1], clamp);

  return (
    <Stage>
      <SceneMeta chapter="ONE RULE" index="01" />

      <div style={{opacity: bodyFade}}>
        <div style={{position: 'absolute', left: 120, top: 190}}>
          <Kicker delay={8}>THE GRAMMAR   语法</Kicker>
          <div style={{height: 38}} />
          <div style={{width: 880}}>
            <GramLine
              delay={30}
              lhs="M"
              arrow="::="
              rhs={<span>x</span>}
              note="变量  variable"
              active
            />
            <GramLine
              delay={55}
              lhs=""
              arrow="|"
              rhs={
                <span>
                  λx. <span style={{color: C.dim}}>M</span>
                </span>
              }
              note="抽象  abstraction"
            />
            <GramLine
              delay={80}
              lhs=""
              arrow="|"
              rhs={
                <span>
                  M <span style={{color: C.dim}}>M</span>
                </span>
              }
              note="应用  application"
            />
          </div>
          <div style={{height: 30}} />
          <Reveal delay={120} y={10}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 24, color: C.dim}}>
              三个动作 构成全部表达式
            </div>
          </Reveal>
        </div>

        <div style={{position: 'absolute', left: 1180, top: 218, width: 620}}>
          <Kicker delay={250}>THE ONLY COMPUTATION RULE</Kicker>
          <div style={{height: 26}} />
          <Reveal delay={270} y={16}>
            <div
              style={{
                borderTop: `1px solid ${C.borderStrong}`,
                borderBottom: `1px solid ${C.border}`,
                padding: '26px 0',
                fontFamily: FONT_MONO,
                fontSize: 31,
                lineHeight: 1.8,
                whiteSpace: 'nowrap',
              }}
            >
              <div>(λx. M) N</div>
              <div style={{color: C.faint}}>→ M[x := N]</div>
            </div>
          </Reveal>
          <div style={{height: 18}} />
          <Reveal delay={330} y={12}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 24, color: C.dim}}>
              把参数 N 放进 M 中所有自由出现的 x
              <br />
              这叫 β 归约
            </div>
          </Reveal>
          <div style={{height: 50}} />
          <Reveal delay={420} y={12}>
            <Label color={C.faint}>计算 = 替换</Label>
            <div
              style={{
                marginTop: 14,
                fontFamily: FONT_SERIF,
                fontSize: 34,
                lineHeight: 1.55,
              }}
            >
              没有循环
              <br />
              没有赋值
              <br />
              没有类型
            </div>
          </Reveal>
        </div>

        <div style={{position: 'absolute', left: 120, top: 700, width: 1640}}>
          <Rule delay={560} duration={36} color={C.border} />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 38,
              paddingTop: 30,
            }}
          >
            <Reveal delay={580} y={12}>
              <Label color={C.faint}>SUBSTITUTION   替换</Label>
            </Reveal>
            <div
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                gap: 26,
                fontFamily: FONT_MONO,
                fontSize: 32,
                whiteSpace: 'nowrap',
              }}
            >
              <span>(λx. </span>
              <span
                style={{
                  position: 'relative',
                  display: 'inline-block',
                  padding: '0 4px',
                  color: C.text,
                }}
              >
                {'x x'}
                <span
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    bottom: -4,
                    height: 2,
                    background: C.text,
                    transform: `scaleX(${substitutionHighlight})`,
                    transformOrigin: 'left',
                  }}
                />
              </span>
              <span>) (λy. y)</span>
              <span style={{color: C.faint}}>→</span>
              <span
                style={{
                  padding: '4px 8px',
                  border: `1px solid ${C.borderStrong}`,
                  background: C.wash,
                }}
              >
                (λy. y)
              </span>
              <span
                style={{
                  padding: '4px 8px',
                  border: `1px solid ${C.borderStrong}`,
                  background: C.wash,
                }}
              >
                (λy. y)
              </span>
            </div>
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: endFade,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{textAlign: 'center', marginTop: -40}}>
          <div
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 92,
              lineHeight: 1.35,
            }}
          >
            一条规则 反复使用
          </div>
          <div style={{height: 30}} />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 42,
              fontFamily: FONT_MONO,
              fontSize: 24,
              color: C.dim,
            }}
          >
            <span>加法</span>
            <span>乘法</span>
            <span>递归</span>
            <span>数据结构</span>
            <span>图灵完备</span>
          </div>
          <div style={{height: 70}} />
          <div
            style={{
              fontFamily: FONT_LATIN,
              fontSize: 28,
              letterSpacing: '0.18em',
              color: C.faint,
            }}
          >
            A TURING-COMPLETE LANGUAGE WITH ONE RULE
          </div>
        </div>
      </div>
    </Stage>
  );
};
