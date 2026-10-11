import { Tooltip } from '@mantine/core'
import { IconCertificate, IconLock } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'

import classes from './config.module.css'
import { tokenize } from './ios'

/** Where a secret was: a chip, never the value (the API does not send it). */
export function RedactedMarker({ kind }: { kind: 'secret' | 'cert' }) {
  const { t } = useTranslation()
  const label = kind === 'cert' ? t('configs.redaction.certificate') : t('configs.redaction.secret')
  const IconComponent = kind === 'cert' ? IconCertificate : IconLock
  return (
    <Tooltip label={t('configs.redaction.hint')} withinPortal>
      <span className={classes.redacted} data-redacted={kind} aria-label={label} role="img">
        <IconComponent size={11} aria-hidden />
        {label}
      </span>
    </Tooltip>
  )
}

/** One configuration line with IOS highlighting and redaction markers. */
export function IosLine({ text }: { text: string }) {
  return (
    <>
      {tokenize(text).map((token, index) =>
        token.kind === 'secret' || token.kind === 'cert' ? (
          <RedactedMarker key={index} kind={token.kind} />
        ) : token.kind === 'plain' ? (
          token.text
        ) : (
          <span key={index} className={classes[token.kind]}>
            {token.text}
          </span>
        ),
      )}
    </>
  )
}
