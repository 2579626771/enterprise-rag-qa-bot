import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FeedbackView from './FeedbackView.vue'

const listMyFeedbackMock = vi.hoisted(() => vi.fn())
const createFeedbackMock = vi.hoisted(() => vi.fn())
const uploadFeedbackScreenshotsMock = vi.hoisted(() => vi.fn())
const closeFeedbackMock = vi.hoisted(() => vi.fn())

vi.mock('../api/client', () => ({
  closeFeedback: closeFeedbackMock,
  createFeedback: createFeedbackMock,
  extractErrorMessage: (err: unknown) => (err instanceof Error ? err.message : '请求失败'),
  listMyFeedback: listMyFeedbackMock,
  openFeedbackAttachment: vi.fn(),
  uploadFeedbackScreenshots: uploadFeedbackScreenshotsMock,
}))

describe('FeedbackView', () => {
  beforeEach(() => {
    listMyFeedbackMock.mockResolvedValue([])
    createFeedbackMock.mockReset()
    uploadFeedbackScreenshotsMock.mockReset()
    closeFeedbackMock.mockReset()
  })

  it('rejects unsupported screenshot formats before submit', async () => {
    const wrapper = mount(FeedbackView)
    await Promise.resolve()

    await wrapper.find('button.primary.lg').trigger('click')
    const input = wrapper.find('input[type="file"]')
    const badFile = new File(['<svg></svg>'], 'bad.svg', { type: 'image/svg+xml' })
    Object.defineProperty(input.element, 'files', { value: [badFile], configurable: true })
    await input.trigger('change')

    expect(wrapper.text()).toContain('不支持的截图格式：bad.svg')
    expect(createFeedbackMock).not.toHaveBeenCalled()
  })

  it('submits feedback then uploads selected screenshots', async () => {
    createFeedbackMock.mockResolvedValue({ id: 11, title: '上传失败' })
    uploadFeedbackScreenshotsMock.mockResolvedValue([])
    const wrapper = mount(FeedbackView)
    await Promise.resolve()

    await wrapper.find('button.primary.lg').trigger('click')
    await wrapper.find('input[placeholder="如：上传 PDF 后一直处理中"]').setValue('上传失败')
    await wrapper.find('textarea').setValue('PDF 上传后一直处理中')

    const input = wrapper.find('input[type="file"]')
    const image = new File(['fake'], 'shot.png', { type: 'image/png' })
    Object.defineProperty(input.element, 'files', { value: [image], configurable: true })
    await input.trigger('change')
    await wrapper.find('.modal-foot .primary').trigger('click')
    await Promise.resolve()
    await Promise.resolve()

    expect(createFeedbackMock).toHaveBeenCalledWith('上传失败', 'PDF 上传后一直处理中')
    expect(uploadFeedbackScreenshotsMock).toHaveBeenCalledWith(11, [image])
  })
})
