import React from 'react';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from './theme';
import {Label, LambdaGlyph, Stage} from './components/core';
import {FontFaces} from './components/ui';

export const Cover: React.FC = () => {
  return (
    <Stage>
      <FontFaces />
      <div
        style={{
          position: 'absolute',
          top: 64,
          left: 80,
          right: 80,
          display: 'flex',
          justifyContent: 'space-between',
          borderBottom: `1px solid ${C.border}`,
          paddingBottom: 18,
          fontFamily: FONT_MONO,
          fontSize: 16,
          letterSpacing: '0.18em',
          color: C.faint,
          textTransform: 'uppercase',
        }}
      >
        <span>A VISUAL ESSAY   2026</span>
        <span>HASKELL   λ</span>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          top: 250,
          display: 'flex',
          alignItems: 'center',
          gap: 90,
        }}
      >
        <LambdaGlyph size={330} delay={-20} duration={1} />
        <div>
          <div style={{fontFamily: FONT_SERIF, fontSize: 104, lineHeight: 1.22}}>
            Lambda 演算解释器
          </div>
          <div
            style={{
              marginTop: 22,
              fontFamily: FONT_LATIN,
              fontSize: 30,
              letterSpacing: '0.16em',
              color: C.dim,
            }}
          >
            LAMBDA CALCULUS INTERPRETER
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          bottom: 220,
          width: 900,
          borderLeft: `2px solid ${C.borderStrong}`,
          paddingLeft: 28,
        }}
      >
        <div style={{fontFamily: FONT_SERIF, fontSize: 46, lineHeight: 1.5}}>
          一条规则
          <br />
          写出整个世界
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          right: 120,
          bottom: 220,
          width: 620,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 10,
          fontFamily: FONT_MONO,
          fontSize: 18,
          lineHeight: 1.7,
          color: C.faint,
        }}
      >
        <div>(λx. M) N → M[x := N]</div>
        <div style={{display: 'flex', gap: 18}}>
          <span>归约轨迹</span>
          <span>任选 redex</span>
          <span>四种策略</span>
        </div>
        <div style={{display: 'flex', gap: 18}}>
          <span>类型推断</span>
          <span>AST</span>
          <span>中英双语</span>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 80,
          right: 80,
          bottom: 52,
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: FONT_MONO,
          fontSize: 14,
          letterSpacing: '0.16em',
          color: C.faint,
          textTransform: 'uppercase',
        }}
      >
        <Label color={C.faint}>A MICROSCOPE FOR REDUCTION</Label>
        <span style={{display: 'flex', gap: 18}}>
          <span>06:22</span>
          <span>1920 × 1080</span>
        </span>
      </div>
    </Stage>
  );
};
