import { ScrollArea } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import classes from './config.module.css'
import { IosLine } from './ConfigText'

/** A redacted configuration with line numbers and IOS highlighting. */
export function ConfigViewer({ content }: { content: string }) {
  const { t } = useTranslation()
  const lines = content.replace(/\n$/, '').split('\n')
  return (
    <ScrollArea.Autosize mah={640} type="auto">
      <table className={classes.code} aria-label={t('configs.viewer.label')}>
        <tbody>
          {lines.map((line, index) => (
            <tr key={index}>
              <td className={classes.number}>{index + 1}</td>
              <td>
                <IosLine text={line} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollArea.Autosize>
  )
}
