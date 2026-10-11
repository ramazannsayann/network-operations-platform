import { Badge, Group, ScrollArea, Text } from '@mantine/core'
import { Fragment, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import classes from './config.module.css'
import { IosLine } from './ConfigText'
import { type DiffLine, parseUnifiedDiff, sideBySide } from './diff'

export type DiffMode = 'unified' | 'split'

const SIGN = { add: '+', del: '−', context: ' ' } as const

function Cells({ line, side }: { line: DiffLine | null; side: 'left' | 'right' }) {
  const { t } = useTranslation()
  if (line === null) {
    return (
      <>
        <td className={`${classes.number} ${classes.empty}`} />
        <td className={`${classes.sign} ${classes.empty}`} />
        <td className={`${classes.half} ${classes.empty}`} />
      </>
    )
  }
  const tone = line.type === 'context' ? '' : classes[line.type]
  return (
    <>
      <td className={`${classes.number} ${tone}`}>
        {side === 'left' ? line.oldNumber : line.newNumber}
      </td>
      <td
        className={`${classes.sign} ${tone}`}
        aria-label={line.type === 'context' ? undefined : t(`configs.diff.${line.type}`)}
      >
        {SIGN[line.type]}
      </td>
      <td className={`${classes.half} ${tone}`}>
        <IosLine text={line.text} />
      </td>
    </>
  )
}

/** The redacted unified diff from the API, as a unified or a side-by-side view. */
export function DiffView({
  text,
  added,
  removed,
  mode,
}: {
  text: string
  added: number
  removed: number
  mode: DiffMode
}) {
  const { t } = useTranslation()
  const diff = useMemo(() => parseUnifiedDiff(text), [text])
  if (diff.hunks.length === 0) {
    return <Text c="dimmed">{t('configs.diff.identical')}</Text>
  }
  return (
    <div data-testid="config-diff">
      <Group gap="xs" mb="xs">
        <Badge color="teal" variant="light">
          {t('configs.diff.addedCount', { count: added })}
        </Badge>
        <Badge color="red" variant="light">
          {t('configs.diff.removedCount', { count: removed })}
        </Badge>
        <Text size="xs" c="dimmed" className="mono">
          {diff.fromLabel} → {diff.toLabel}
        </Text>
      </Group>
      <ScrollArea.Autosize mah={640} type="auto">
        <table
          className={`${classes.code} ${mode === 'split' ? classes.split : ''}`}
          aria-label={t(mode === 'split' ? 'configs.diff.split' : 'configs.diff.unified')}
        >
          <tbody>
            {diff.hunks.map((hunk, index) => (
              <Fragment key={index}>
                <tr className={classes.hunk}>
                  <td colSpan={mode === 'split' ? 6 : 4}>{hunk.header}</td>
                </tr>
                {mode === 'split'
                  ? sideBySide(hunk).map((row, rowIndex) => (
                      <tr key={rowIndex} data-row="split">
                        <Cells line={row.left} side="left" />
                        <Cells line={row.right} side="right" />
                      </tr>
                    ))
                  : hunk.lines.map((line, lineIndex) => {
                      const tone = line.type === 'context' ? '' : classes[line.type]
                      return (
                        <tr key={lineIndex} data-change={line.type}>
                          <td className={`${classes.number} ${tone}`}>{line.oldNumber}</td>
                          <td className={`${classes.number} ${tone}`}>{line.newNumber}</td>
                          <td
                            className={`${classes.sign} ${tone}`}
                            aria-label={
                              line.type === 'context' ? undefined : t(`configs.diff.${line.type}`)
                            }
                          >
                            {SIGN[line.type]}
                          </td>
                          <td className={tone}>
                            <IosLine text={line.text} />
                          </td>
                        </tr>
                      )
                    })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </ScrollArea.Autosize>
    </div>
  )
}
