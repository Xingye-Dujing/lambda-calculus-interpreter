import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  LambdaGlyph,
  SceneMeta,
  Stage,
} from '../components/core';

export const Ending: React.FC = () => {
  const frame = useCurrentFrame();
  const bodyOut = interpolate(frame, [420, 500], [1, 0], clamp);
  const darkIn = interpolate(frame, [470, 550], [0, 1], clamp);
  const final = interpolate(frame, [560, 620], [0, 1], clamp);

  return (
    <Stage>
      <SceneMeta chapter="CODA" index="08" />

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: bodyOut,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{width: 1320}}>
          <Kicker delay={8}>CODA   收尾</Kicker>
          <div style={{height: 32}} />
          <div style={{display: 'flex', alignItems: 'center', gap: 80}}>
            <LambdaGlyph size={240} delay={20} duration={40} />
            <div>
              <div style={{fontFamily: FONT_SERIF, fontSize: 72, lineHeight: 1.4}}>
                λ 是世界上最简单的
                <br />
                语言之一
              </div>
              <div style={{height: 30}} />
              <div style={{fontFamily: FONT_SERIF, fontSize: 30, color: C.dim, lineHeight: 1.8}}>
                它不急着给你答案
                <br />
                它把答案怎么出现
                <br />
                交给你看
              </div>
            </div>
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: C.dark,
          color: C.darkText,
          opacity: darkIn,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{textAlign: 'center', opacity: final}}>
          <LambdaGlyph
            size={96}
            delay={520}
            duration={28}
            color={C.darkText}
            style={{margin: '0 auto 22px'}}
          />
          <div style={{fontFamily: FONT_SERIF, fontSize: 64, letterSpacing: '0.04em'}}>
            Lambda 演算解释器
          </div>
          <div
            style={{
              marginTop: 18,
              fontFamily: FONT_MONO,
              fontSize: 20,
              letterSpacing: '0.04em',
              color: C.darkDim,
            }}
          >
            github.com/Xingye-Dujing/lambda-calculus-interpreter
          </div>
          <div style={{height: 38}} />
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 16,
              fontFamily: FONT_SERIF,
              fontSize: 22,
              color: C.darkFaint,
            }}
          >
            <span style={{width: 44, height: 1, background: C.darkBorderStrong}} />
            如果它也让你多看了一眼计算
            <span style={{width: 44, height: 1, background: C.darkBorderStrong}} />
          </div>
          <div
            style={{
              marginTop: 18,
              fontFamily: FONT_SERIF,
              fontSize: 22,
              color: C.darkDim,
            }}
          >
            欢迎 star
          </div>
        </div>
      </div>
    </Stage>
  );
};
