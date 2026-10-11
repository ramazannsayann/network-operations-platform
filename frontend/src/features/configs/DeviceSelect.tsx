import { Select } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { useDevices } from '../../api/queries'

/** Filter by device: the managed devices, by hostname. */
export function DeviceSelect({
  value,
  onChange,
}: {
  value: string | null
  onChange: (id: string | null) => void
}) {
  const { t } = useTranslation()
  const devices = useDevices({ sort: 'hostname', limit: 500, management_status: ['managed'] })
  return (
    <Select
      label={t('filters.device')}
      placeholder={t('common.all')}
      data={(devices.data?.items ?? []).map((device) => ({
        value: device.id,
        label: device.hostname ?? device.mgmt_ip ?? device.id,
      }))}
      value={value}
      onChange={onChange}
      searchable
      clearable
      w={200}
    />
  )
}
