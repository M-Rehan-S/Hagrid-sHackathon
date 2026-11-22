import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useT } from '../../components/Shared'
import { draftKey, queueKey, readLocal } from '../../offline/store'

const { api } = vi.hoisted(() => ({ api: {
  cases: vi.fn(), citizen: vi.fn(), createCitizen: vi.fn(), createCase: vi.fn(), case: vi.fn(),
  patchForm: vi.fn(), submitCase: vi.fn(), uploadDocument: vi.fn(),
} }))
vi.mock('../../api/client', () => ({ api }))

import { CasesView } from './CitizenViews'

const profile = { id: 'user-1', full_name: 'Demo Citizen', role: 'citizen' }
const language = 'en'
const citizen = { id: 'citizen-1', full_name: 'Fatima Bibi', user_id: profile.id }
const t = (key, values) => useT(language)(key, values)

describe('citizen application journey', () => {
  beforeEach(() => {
    localStorage.clear()
    api.cases.mockResolvedValue([])
    api.citizen.mockResolvedValue(citizen)
    api.createCitizen.mockResolvedValue({ citizen })
    api.createCase.mockResolvedValue({ id: 'case-1', citizen_id: citizen.id, status: 'draft', form_data: {}, missing_fields: [] })
    api.case.mockResolvedValue({ id: 'case-1', citizen_id: citizen.id, status: 'draft', form_data: {}, missing_fields: [], decisions: [], events: [] })
    api.patchForm.mockImplementation(async (_id, partial) => ({ case: { id: 'case-1', status: 'draft', form_data: partial }, missing_fields: [] }))
    api.submitCase.mockResolvedValue({ case: { id: 'case-1', status: 'submitted' }, decision: { outcome: 'human_review' } })
  })
  afterEach(() => { cleanup(); vi.clearAllMocks(); Object.defineProperty(navigator, 'onLine', { configurable: true, value: true }) })

  it('creates a citizen profile, starts a claim, and saves each wizard step through the proposal API', async () => {
    const user = userEvent.setup()
    render(<CasesView profile={profile} language={language} t={t} selectedCitizen={null} onNavigate={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: 'Before we start' })).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Full name'))
    await user.type(screen.getByLabelText('Full name'), 'Fatima Bibi')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('heading', { name: 'Your applications' })).toBeInTheDocument()
    expect(api.createCitizen).toHaveBeenCalledWith({ full_name: 'Fatima Bibi' })
    await user.click(screen.getAllByRole('button', { name: /New application/ })[0])
    expect(await screen.findByRole('heading', { name: 'What is your CNIC number?' })).toBeInTheDocument()
    expect(api.createCase).toHaveBeenCalledWith(citizen.id)
    const questionPanel = screen.getByRole('heading', { name: 'What is your CNIC number?' }).closest('.question-panel')
    const progress = screen.getByText('Question 1 of 10').closest('.form-progress')
    expect(questionPanel.compareDocumentPosition(progress) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    expect(await screen.findByText('Enter all 13 digits of your CNIC to continue.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('CNIC (13 digits)'), '4210112345671')
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    await waitFor(() => expect(api.patchForm).toHaveBeenCalledWith('case-1', { cnic: '4210112345671' }, 'cnic'))
    expect(await screen.findByRole('heading', { name: 'What is your full name?' })).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveValue('Fatima Bibi')
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByLabelText('CNIC (13 digits)')).toHaveValue('4210112345671')
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    expect(await screen.findByRole('heading', { name: 'What is your full name?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    await waitFor(() => expect(api.patchForm).toHaveBeenCalledWith('case-1', { full_name: 'Fatima Bibi' }, 'full_name'))
    expect(await screen.findByRole('heading', { name: "What is your father's or guardian's name?" })).toBeInTheDocument()
  })

  it('submits the draft and renders its current status as a receipt', async () => {
    localStorage.setItem(`citizen-id:${profile.id}`, citizen.id)
    const user = userEvent.setup()
    render(<CasesView profile={profile} language={language} t={t} selectedCitizen={null} onNavigate={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: 'Your applications' })).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /New application/ })[0])
    expect(await screen.findByRole('heading', { name: 'What is your CNIC number?' })).toBeInTheDocument()

    const answers = [
      ['CNIC (13 digits)', '4210112345671'], ['Full name', 'Fatima Bibi'],
      ['Father or guardian name', 'Muhammad Aslam'], ['Date of birth', '1978-04-12'],
      ['District', 'Karachi East'], ['People in household', '5'], ['Monthly income (PKR)', '18000'],
    ]
    for (const [label, value] of answers) {
      const field = screen.getByLabelText(label)
      if (label === 'District') await user.selectOptions(field, value)
      else { if (label === 'Full name') await user.clear(field); await user.type(field, value) }
      await user.click(screen.getByRole('button', { name: /^Next/ }))
    }
    await user.click(document.querySelector('.choice-row button'))
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    await user.type(screen.getByLabelText('Phone number'), '03001234567')
    await user.click(screen.getByRole('button', { name: /^Next/ }))
    expect(await screen.findByRole('heading', { name: 'Add a CNIC photo or supporting document (optional).' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Send application' }))

    expect(api.submitCase).toHaveBeenCalledWith('case-1')
    expect((await screen.findAllByText('Submitted')).length).toBeGreaterThan(0)
  })

  it('shows the officer-written rejection reason on the citizen receipt', async () => {
    localStorage.setItem(`citizen-id:${profile.id}`, citizen.id)
    api.cases.mockResolvedValue([{ id: 'case-1', citizen_id: citizen.id, status: 'rejected', form_data: { full_name: 'Fatima Bibi' } }])
    api.case.mockResolvedValue({
      id: 'case-1', citizen_id: citizen.id, status: 'rejected', form_data: { full_name: 'Fatima Bibi' },
      decisions: [{ id: 'decision-1', actor_type: 'officer', outcome: 'rejected', reason_en: 'An officer declined this claim after review.' }],
      events: [{ id: 'event-1', event_type: 'decision', note: 'Your monthly income is above the program limit.' }],
    })
    const user = userEvent.setup()
    render(<CasesView profile={profile} language={language} t={t} selectedCitizen={null} onNavigate={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /Fatima Bibi/ }))

    expect(await screen.findByRole('heading', { name: 'Why the officer rejected this application' })).toBeInTheDocument()
    expect(screen.getAllByText('Your monthly income is above the program limit.').length).toBeGreaterThan(0)
  })

  it('starts a local claim offline and stores answers until the create operation can sync', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    localStorage.setItem(`citizen-id:${profile.id}`, citizen.id)
    const user = userEvent.setup()
    render(<CasesView profile={profile} language={language} t={t} selectedCitizen={null} onNavigate={vi.fn()} />)
    await user.click((await screen.findAllByRole('button', { name: /New application/ }))[0])
    expect(await screen.findByRole('heading', { name: 'What is your CNIC number?' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('CNIC (13 digits)'), '4210112345671')
    await user.click(screen.getByRole('button', { name: /^Next/ }))

    const queued = await readLocal(queueKey(profile.id), [])
    const cachedCases = await readLocal(`cases:${profile.id}`, [])
    const localCase = cachedCases.find((item) => item.id.startsWith('local-'))
    const draft = await readLocal(draftKey(profile.id, localCase.id), null)
    expect(api.createCase).not.toHaveBeenCalled()
    expect(queued).toHaveLength(1)
    expect(queued[0]).toMatchObject({ type: 'create_case', payload: { citizen_id: citizen.id, case_type: 'relief_claim' } })
    expect(draft).toMatchObject({ cnic: '4210112345671' })
  })
})
