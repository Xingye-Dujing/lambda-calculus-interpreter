import React, {ReactNode} from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  Label,
  Panel,
  Reveal,
  SceneMeta,
  Stage,
  Typewriter,
} from '../components/core';
import {
  AppWindow,
  Cursor,
  MiniTrace,
  RedexRow,
  TermLine,
} from '../components/ui';

const layerOpacity = (frame: number, from: number, to: number) =>
  interpolate(frame, [from, from + 26, to - 26, to], [0, 1, 1, 0], clamp);

const StepRow: React.FC<{n: number; text: string; active?: boolean; delay?: number}> = ({
  n,
  text,
  active = false,
  delay = 0,
}) => (
  <Reveal delay={delay} y={8} duration={14}>
    <div
      style={{
        display: 'flex',
        gap: 12,
        padding: '6px 10px',
        borderLeft: `1px solid ${active ? C.text : 'transparent'}`,
        background: active ? C.wash : 'transparent',
        fontFamily: FONT_MONO,
        fontSize: 16,
        color: active ? C.text : C.faint,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      <span style={{width: 18, color: C.faint}}>{n}.</span>
      <span style={{overflow: 'hidden', textOverflow: 'ellipsis'}}>{text}</span>
    </div>
  </Reveal>
);

const FeatureCard: React.FC<{
  title: string;
  en: string;
  body: string;
  command: string;
  delay: number;
  highlight?: boolean;
}> = ({title, en, body, command, delay, highlight = false}) => (
  <Reveal delay={delay} y={16} duration={20}>
    <div
      style={{
        border: `1px solid ${highlight ? C.borderStrong : C.border}`,
        background: highlight ? C.wash : C.paper,
        padding: '24px 24px 22px',
        height: 188,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{display: 'flex', alignItems: 'baseline', gap: 12}}>
        <span style={{fontFamily: FONT_SERIF, fontSize: 28}}>{title}</span>
        <span
          style={{
            fontFamily: FONT_LATIN,
            fontSize: 15,
            fontStyle: 'italic',
            color: C.faint,
          }}
        >
          {en}
        </span>
        <span style={{flex: 1}} />
        <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
          {command}
        </span>
      </div>
      <div
        style={{
          marginTop: 14,
          fontFamily: FONT_SERIF,
          fontSize: 19,
          lineHeight: 1.65,
          color: C.dim,
          whiteSpace: 'pre-line',
        }}
      >
        {body}
      </div>
    </div>
  </Reveal>
);

export const Demo: React.FC = () => {
  const frame = useCurrentFrame();
  const appOpacity = interpolate(frame, [1560, 1640], [1, 0], clamp);
  const summaryOpacity = interpolate(frame, [1600, 1680], [0, 1], clamp);
  const phaseA = layerOpacity(frame, 0, 430);
  const phaseB = layerOpacity(frame, 420, 840);
  const phaseC = layerOpacity(frame, 830, 1220);
  const phaseD = layerOpacity(frame, 1210, 1580);

  const activeTab =
    frame < 830 ? '轨迹' : frame < 1220 ? '工具' : frame < 1580 ? '结构' : '轨迹';

  const content: ReactNode = (
    <>
      <div style={{position: 'absolute', inset: 0, opacity: phaseA}}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.12fr 0.88fr',
            height: '100%',
          }}
        >
          <div style={{padding: '28px 30px', borderRight: `1px solid ${C.border}`}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22}}>
              <Label color={C.faint}>TERMINAL   REPL</Label>
              <span style={{flex: 1}} />
              <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
                strategy: applicative
              </span>
            </div>
            <TermLine prompt="λ>" tone="normal" size={24}>
              <Typewriter text="id = \x.x" delay={40} speed={1.1} />
            </TermLine>
            <TermLine tone="dim" size={20} delay={150}>
              已定义 id = λx → x  defined id = λx → x
            </TermLine>
            <div style={{height: 18}} />
            <TermLine prompt="λ>" tone="normal" size={24}>
              <Typewriter text="PLUS TWO THREE" delay={190} speed={1.25} />
            </TermLine>
            <Reveal delay={300} y={8}>
              <div
                style={{
                  marginTop: 14,
                  fontFamily: FONT_MONO,
                  fontSize: 28,
                  color: C.text,
                }}
              >
                <span style={{color: C.faint}}>⇒ </span>
                λf → λx → f (f (f (f (f x))))
              </div>
            </Reveal>
            <Reveal delay={350} y={6}>
              <div
                style={{
                  marginTop: 10,
                  marginLeft: 34,
                  fontFamily: FONT_MONO,
                  fontSize: 16,
                  color: C.faint,
                }}
              >
                6 步  6 steps    邱奇数 5  Church numeral 5
              </div>
            </Reveal>
            <div style={{height: 30}} />
            <Reveal delay={390} y={8}>
              <div
                style={{
                  borderTop: `1px dashed ${C.border}`,
                  paddingTop: 18,
                  fontFamily: FONT_SERIF,
                  fontSize: 20,
                  color: C.dim,
                }}
              >
                同一条命令
                <br />
                左边给结果 右边给过程
              </div>
            </Reveal>
          </div>
          <div style={{padding: '26px 28px', background: C.bg}}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                marginBottom: 18,
              }}
            >
              <Label color={C.faint}>TRACE   轨迹</Label>
              <span style={{flex: 1}} />
              <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
                第 1 步  共 6 步
              </span>
            </div>
            <MiniTrace
              step={1}
              total={6}
              rule="β"
              before="(λm.λn.λf.λx. m f (n f x)) TWO THREE"
              after="(λn.λf.λx. TWO f (n f x)) THREE"
              delay={330}
              width={520}
            />
            <div style={{height: 20}} />
            {[
              '(λn.λf.λx. TWO f (n f x)) THREE',
              '(λf.λx. TWO f (THREE f x))',
              '(λf.λx. f (f (THREE f x)))',
              'λf.λx. f (f (f (f (f x))))',
            ].map((t, i) => (
              <StepRow key={t} n={i + 2} text={t} delay={390 + i * 30} />
            ))}
          </div>
        </div>
      </div>

      <div style={{position: 'absolute', inset: 0, opacity: phaseB}}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.12fr 0.88fr',
            height: '100%',
          }}
        >
          <div style={{padding: '28px 30px', borderRight: `1px solid ${C.border}`}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22}}>
              <Label color={C.faint}>MANUAL REDUCTION   手动归约</Label>
              <span style={{flex: 1}} />
              <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
                redexCount: 2
              </span>
            </div>
            <TermLine prompt="λ>" tone="normal" size={24}>
              <Typewriter
                text=":begin (\x.x) ((\y.y) z)"
                delay={445}
                speed={1.05}
              />
            </TermLine>
            <div style={{height: 18}} />
            <Reveal delay={560} y={8}>
              <div
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 19,
                  color: C.dim,
                  lineHeight: 1.8,
                }}
              >
                当前项  current term
                <br />
                <span style={{color: C.text}}>(λx. x) ((λy. y) z)</span>
              </div>
            </Reveal>
            <div style={{height: 26}} />
            <TermLine prompt="λ>" tone="normal" size={24} delay={700}>
              <Typewriter text=":step 2" delay={720} speed={1.2} />
            </TermLine>
            <Reveal delay={820} y={8}>
              <div
                style={{
                  marginTop: 14,
                  fontFamily: FONT_MONO,
                  fontSize: 25,
                  color: C.text,
                }}
              >
                <span style={{color: C.faint}}>⇒ </span>
                (λx. x) z
              </div>
            </Reveal>
            <Reveal delay={870} y={8}>
              <div
                style={{
                  marginTop: 10,
                  marginLeft: 34,
                  fontFamily: FONT_MONO,
                  fontSize: 16,
                  color: C.faint,
                }}
              >
                还可以继续  路径由你决定
              </div>
            </Reveal>
          </div>
          <div style={{padding: '26px 28px', background: C.bg}}>
            <div style={{display: 'flex', alignItems: 'center', marginBottom: 16}}>
              <Label color={C.faint}>REDEXES   可归约位置</Label>
              <span style={{flex: 1}} />
              <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
                click to reduce
              </span>
            </div>
            <RedexRow
              index={1}
              path="root"
              term="(λx.x) ((λy.y) z)"
              active={false}
              delay={560}
            />
            <RedexRow
              index={2}
              path="1"
              term="(λy.y) z"
              active
              delay={600}
              onClickPulse={680}
            />
            <Cursor
              x={1390}
              y={148}
              fromX={1510}
              fromY={360}
              delay={600}
              duration={38}
              clickAt={680}
            />
            <div style={{height: 24}} />
            <Reveal delay={760} y={8}>
              <div
                style={{
                  fontFamily: FONT_SERIF,
                  fontSize: 20,
                  color: C.dim,
                  lineHeight: 1.7,
                  borderTop: `1px dashed ${C.border}`,
                  paddingTop: 18,
                }}
              >
                先归约根节点 还是先归约参数
                <br />
                同一个项 不同的中间形态
              </div>
            </Reveal>
          </div>
        </div>
      </div>

      <div style={{position: 'absolute', inset: 0, opacity: phaseC, padding: '28px 30px'}}>
        <div style={{display: 'flex', alignItems: 'center', marginBottom: 20}}>
          <Label color={C.faint}>TOOLS   工具</Label>
          <span style={{flex: 1}} />
          <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
            four strategies  fast normalization  HM types
          </span>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 16,
          }}
        >
          <FeatureCard
            title="四种策略"
            en="strategies"
            body={'应用序 正规序 按名调用 按值调用\n换一条路 看到的中间形态完全不同'}
            command=":strategy"
            delay={860}
            highlight
          />
          <FeatureCard
            title="快速模式"
            en="fast"
            body={'de Bruijn 加闭包 加共享 thunk\n大数 Church 运算只给正规形 把时间留给结果'}
            command=":fast on"
            delay={900}
          />
          <FeatureCard
            title="类型推断"
            en="Hindley–Milner"
            body={'从项本身推出类型 支持 let 泛化\n类型不是装饰 是另一种结构'}
            command=":type"
            delay={940}
          />
          <FeatureCard
            title="双语输出"
            en="bilingual"
            body={'中英两种文本同时生成\n教学 截图 分享 都不必再翻译一遍'}
            command="--lang zh|en|both"
            delay={980}
          />
        </div>
        <div style={{height: 18}} />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 18,
            padding: '12px 0',
            borderTop: `1px solid ${C.border}`,
          }}
        >
          <span style={{fontFamily: FONT_MONO, fontSize: 18, color: C.faint}}>λ&gt;</span>
          <span style={{fontFamily: FONT_MONO, fontSize: 20, color: C.text}}>
            <Typewriter text=":type \f.\x.f (f x)" delay={1040} speed={1.2} />
          </span>
          <span style={{flex: 1}} />
          <Reveal delay={1160} y={6}>
            <span style={{fontFamily: FONT_MONO, fontSize: 20, color: C.dim}}>
              ⊢ (t0 → t0) → t0 → t0
            </span>
          </Reveal>
        </div>
      </div>

      <div style={{position: 'absolute', inset: 0, opacity: phaseD, padding: '28px 30px'}}>
        <div style={{display: 'flex', alignItems: 'center', marginBottom: 18}}>
          <Label color={C.faint}>STRUCTURE   结构</Label>
          <span style={{flex: 1}} />
          <span style={{fontFamily: FONT_MONO, fontSize: 14, color: C.faint}}>
            AST  de Bruijn  alpha equivalence
          </span>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.05fr 0.95fr',
            gap: 26,
            height: 'calc(100% - 44px)',
          }}
        >
          <Panel padding={22} style={{background: C.bg}}>
            <Label color={C.faint}>ABSTRACT SYNTAX TREE</Label>
            <div style={{height: 16}} />
            <div
              style={{
                fontFamily: FONT_MONO,
                fontSize: 21,
                lineHeight: 1.9,
                color: C.dim,
                whiteSpace: 'pre',
              }}
            >
              <Reveal delay={1240} y={6}>
                <div>λx. x x</div>
              </Reveal>
              <Reveal delay={1280} y={6}>
                <div style={{color: C.text}}>├─ λ x</div>
              </Reveal>
              <Reveal delay={1310} y={6}>
                <div>│&nbsp;&nbsp;└─ App</div>
              </Reveal>
              <Reveal delay={1340} y={6}>
                <div>│&nbsp;&nbsp;&nbsp;&nbsp;├─ x</div>
              </Reveal>
              <Reveal delay={1360} y={6}>
                <div>│&nbsp;&nbsp;&nbsp;&nbsp;└─ x</div>
              </Reveal>
            </div>
            <div style={{height: 26}} />
            <Reveal delay={1410} y={8}>
              <div
                style={{
                  borderTop: `1px dashed ${C.border}`,
                  paddingTop: 16,
                  fontFamily: FONT_MONO,
                  fontSize: 18,
                  color: C.dim,
                }}
              >
                de Bruijn&nbsp;&nbsp;λ.(#0 #0)
              </div>
            </Reveal>
          </Panel>
          <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
            <Reveal delay={1300} y={12}>
              <div
                style={{
                  border: `1px solid ${C.border}`,
                  padding: '20px 22px',
                  fontFamily: FONT_MONO,
                  fontSize: 18,
                  lineHeight: 1.7,
                }}
              >
                <div style={{color: C.faint, fontSize: 13, letterSpacing: '0.12em'}}>
                  ALPHA EQUIVALENCE   α 等价
                </div>
                <div style={{marginTop: 8}}>:eq \a.a , \b.b</div>
                <div style={{color: C.ok}}>true  λa → a ≡ λb → b</div>
              </div>
            </Reveal>
            <Reveal delay={1360} y={12}>
              <div
                style={{
                  border: `1px solid ${C.border}`,
                  padding: '20px 22px',
                  fontFamily: FONT_MONO,
                  fontSize: 18,
                  lineHeight: 1.7,
                }}
              >
                <div style={{color: C.faint, fontSize: 13, letterSpacing: '0.12em'}}>
                  BETA EQUIVALENCE   β 等价
                </div>
                <div style={{marginTop: 8}}>:conv PLUS ONE TWO , THREE</div>
                <div style={{color: C.ok}}>true  两边归约到同一正规形</div>
              </div>
            </Reveal>
            <Reveal delay={1430} y={12}>
              <div
                style={{
                  fontFamily: FONT_SERIF,
                  fontSize: 20,
                  color: C.dim,
                  lineHeight: 1.7,
                  paddingLeft: 2,
                }}
              >
                结构视图不是装饰
                <br />
                它让你看见 一个项究竟由什么组成
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </>
  );

  return (
    <Stage>
      <SceneMeta chapter="THE INSTRUMENT" index="04" />

      <div style={{position: 'absolute', left: 180, top: 168, opacity: appOpacity}}>
        <AppWindow
          width={1560}
          height={690}
          activeTab={activeTab}
          status="已连接  connected"
          style={{position: 'relative'}}
        >
          <div style={{position: 'relative', width: '100%', height: '100%'}}>{content}</div>
        </AppWindow>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 14,
            fontFamily: FONT_MONO,
            fontSize: 14,
            color: C.faint,
            letterSpacing: '0.08em',
          }}
        >
          <span>每个结果都可以展开  every result can be unfolded</span>
          <span>web UI  flask + extension --batch --json</span>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: summaryOpacity,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{width: 1500}}>
          <Kicker delay={1620}>A COMPLETE CHAIN OF OBSERVATION</Kicker>
          <div style={{height: 26}} />
          <div style={{fontFamily: FONT_SERIF, fontSize: 84, lineHeight: 1.35}}>
            一条完整的观察链
          </div>
          <div style={{height: 50}} />
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 0,
              borderTop: `1px solid ${C.borderStrong}`,
              borderBottom: `1px solid ${C.border}`,
            }}
          >
            {[
              ['01', '每一步', 'before  after'],
              ['02', '每个 redex', 'choose the path'],
              ['03', '每种策略', 'see the difference'],
              ['04', '每个结构', 'AST  de Bruijn'],
            ].map(([n, t, en], i) => (
              <Reveal key={n} delay={1700 + i * 50} y={14}>
                <div
                  style={{
                    padding: '28px 26px',
                    borderLeft: i === 0 ? 'none' : `1px solid ${C.border}`,
                    minHeight: 150,
                  }}
                >
                  <div
                    style={{
                      fontFamily: FONT_MONO,
                      fontSize: 14,
                      letterSpacing: '0.14em',
                      color: C.faint,
                    }}
                  >
                    {n}
                  </div>
                  <div style={{fontFamily: FONT_SERIF, fontSize: 34, marginTop: 12}}>
                    {t}
                  </div>
                  <div
                    style={{
                      fontFamily: FONT_MONO,
                      fontSize: 14,
                      color: C.faint,
                      marginTop: 10,
                    }}
                  >
                    {en}
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
          <div style={{height: 32}} />
          <Reveal delay={1880} y={12}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 28, color: C.dim}}>
              结果不是终点
              <span style={{color: C.text}}> 结果如何发生 才是</span>
            </div>
          </Reveal>
        </div>
      </div>
    </Stage>
  );
};
