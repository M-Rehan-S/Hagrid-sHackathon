import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useT } from '../../components/Shared'

const { api } = vi.hoisted(() => ({ api: {
  cases: vi.fn(), case: vi.fn(), decideCase: vi.fn(), escalateCase: vi.fn(), assignCase: vi.fn(), closeCase: vi.fn(),
} }))
vi.mock('../../api/client', () => ({ api }))

import { OfficerView } from './StaffViews'

const t = (key, values) => useT('en')(key, values)
const caseRecord = (status) => ({
  id: 'case-1', citizen_id: 'citizen-1', status, route: 'human_review', confidence: 0.7,
  form_data: { full_name: 'Fatima Bibi' }, decisions: [], events: [],
})

describe('officer case status actions', () => {
  beforeEach(() => {
    api.cases.mockResolvedValue([caseRecord('needs_info')])
    api.case.mockImplementation(async () => caseRecord('needs_info'))
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('explains why an ineligible case cannot be rejected', async () => {
    const user = userEvent.setup()
    render(<OfficerView language="en" t={t} />)
    await user.selectOptions(await screen.findByLabelText('Filter by status'), 'needs_info')
    await user.click(await screen.findByRole('button', { name: /Fatima Bibi/ }))

    expect(await screen.findByRole('heading', { name: 'This application is not ready for a decision' })).toBeInTheDocument()
    expect(screen.getByText(/Current status: More information needed/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reject/ })).not.toBeInTheDocument()
    expect(api.decideCase).not.toHaveBeenCalled()
  })

  it('shows officer decision actions for a submitted case', async () => {
    api.cases.mockResolvedValue([caseRecord('submitted')])
    api.case.mockImplementation(async () => caseRecord('submitted'))
    const user = userEvent.setup()
    render(<OfficerView language="en" t={t} />)
    await user.click(await screen.findByRole('button', { name: /Fatima Bibi/ }))

    expect(await screen.findByRole('button', { name: /Reject/ })).toBeInTheDocument()
  })

  it('keeps drafts out of the actionable queue by default', async () => {
    api.cases.mockResolvedValue([
      { ...caseRecord('draft'), id: 'draft-1', form_data: { full_name: 'Draft Applicant' } },
      caseRecord('submitted'),
    ])
    render(<OfficerView language="en" t={t} />)

    expect(await screen.findByRole('button', { name: /Fatima Bibi/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Draft Applicant/ })).not.toBeInTheDocument()
  })
})
