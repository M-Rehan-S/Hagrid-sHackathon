import { describe, expect, it } from 'vitest'
import { dictionaries, translate } from './index'

describe('language dictionaries', () => {
  it('keep the same keys in English and Urdu', () => {
    expect(Object.keys(dictionaries.ur).sort()).toEqual(Object.keys(dictionaries.en).sort())
  })

  it('interpolates labels without losing names or counts', () => {
    expect(translate('en', 'question_progress', { current: 2, total: 10 })).toBe('Question 2 of 10')
    expect(translate('ur', 'welcome', { name: 'Fatima' })).toContain('Fatima')
  })
})
