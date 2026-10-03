import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  MIN_IMAGE_DIMENSION,
  MAX_IMAGE_DIMENSION,
  DEFAULT_MAX_DIMENSION,
  DEFAULT_COMPRESSION_QUALITY,
  validateImageDimensions,
  compressImage,
} from '@/utils/imageUtils'

describe('imageUtils unit tests', () => {
  const originalCreateObjectURL = window.URL.createObjectURL
  const originalRevokeObjectURL = window.URL.revokeObjectURL
  const originalImage = window.Image
  const originalGetContext = HTMLCanvasElement.prototype.getContext
  const originalToBlob = HTMLCanvasElement.prototype.toBlob

  let createObjectURLMock: ReturnType<typeof vi.fn>
  let revokeObjectURLMock: ReturnType<typeof vi.fn>

  // Configurable mock Image properties
  let mockNaturalWidth = 800
  let mockNaturalHeight = 600
  let mockImageShouldFail = false

  class MockImage {
    naturalWidth = 0
    naturalHeight = 0
    width = 0
    height = 0
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    private _src = ''

    set src(value: string) {
      this._src = value
      queueMicrotask(() => {
        if (mockImageShouldFail) {
          this.onerror?.()
        } else {
          this.naturalWidth = mockNaturalWidth
          this.naturalHeight = mockNaturalHeight
          this.width = mockNaturalWidth
          this.height = mockNaturalHeight
          this.onload?.()
        }
      })
    }

    get src() {
      return this._src
    }
  }

  beforeEach(() => {
    mockNaturalWidth = 800
    mockNaturalHeight = 600
    mockImageShouldFail = false

    createObjectURLMock = vi.fn().mockReturnValue('blob:http://localhost/mock-uuid')
    revokeObjectURLMock = vi.fn()

    window.URL.createObjectURL = createObjectURLMock as unknown as typeof window.URL.createObjectURL
    window.URL.revokeObjectURL = revokeObjectURLMock as unknown as typeof window.URL.revokeObjectURL
    // @ts-expect-error Mocking Image
    window.Image = MockImage
  })

  afterEach(() => {
    window.URL.createObjectURL = originalCreateObjectURL
    window.URL.revokeObjectURL = originalRevokeObjectURL
    window.Image = originalImage
    HTMLCanvasElement.prototype.getContext = originalGetContext
    HTMLCanvasElement.prototype.toBlob = originalToBlob
    vi.restoreAllMocks()
  })

  describe('exported constants', () => {
    it('defines and exports required dimension bounds and default settings', () => {
      expect(MIN_IMAGE_DIMENSION).toBe(50)
      expect(MAX_IMAGE_DIMENSION).toBe(8192)
      expect(DEFAULT_MAX_DIMENSION).toBe(2048)
      expect(DEFAULT_COMPRESSION_QUALITY).toBe(0.85)
    })
  })

  describe('validateImageDimensions', () => {
    it('validates images with standard valid dimensions (800x600)', async () => {
      mockNaturalWidth = 800
      mockNaturalHeight = 600
      const file = new File(['valid-image-bytes'], 'sample.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result).toEqual({
        width: 800,
        height: 600,
        valid: true,
      })
      expect(createObjectURLMock).toHaveBeenCalledWith(file)
      expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:http://localhost/mock-uuid')
    })

    it('accepts minimum dimension boundaries (50x50)', async () => {
      mockNaturalWidth = 50
      mockNaturalHeight = 50
      const file = new File(['min-bounds'], 'min.png', { type: 'image/png' })

      const result = await validateImageDimensions(file)

      expect(result).toEqual({
        width: 50,
        height: 50,
        valid: true,
      })
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('accepts maximum dimension boundaries (8192x8192)', async () => {
      mockNaturalWidth = 8192
      mockNaturalHeight = 8192
      const file = new File(['max-bounds'], 'max.png', { type: 'image/png' })

      const result = await validateImageDimensions(file)

      expect(result).toEqual({
        width: 8192,
        height: 8192,
        valid: true,
      })
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('rejects images below minimum dimension (e.g. 40x40)', async () => {
      mockNaturalWidth = 40
      mockNaturalHeight = 40
      const file = new File(['tiny'], 'tiny.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result.valid).toBe(false)
      expect(result.width).toBe(40)
      expect(result.height).toBe(40)
      expect(result.error).toBe(
        'Image dimensions (40x40) are below minimum required resolution of 50x50 pixels.'
      )
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('rejects images where width is below 50 but height is large (e.g. 45x1200)', async () => {
      mockNaturalWidth = 45
      mockNaturalHeight = 1200
      const file = new File(['thin'], 'thin.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result.valid).toBe(false)
      expect(result.width).toBe(45)
      expect(result.height).toBe(1200)
      expect(result.error).toBe(
        'Image dimensions (45x1200) are below minimum required resolution of 50x50 pixels.'
      )
    })

    it('rejects images exceeding maximum dimension (e.g. 8193x6000)', async () => {
      mockNaturalWidth = 8193
      mockNaturalHeight = 6000
      const file = new File(['huge'], 'huge.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result.valid).toBe(false)
      expect(result.width).toBe(8193)
      expect(result.height).toBe(6000)
      expect(result.error).toBe(
        'Image dimensions (8193x6000) exceed maximum allowed resolution of 8192x8192 pixels.'
      )
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('handles image decoding failures gracefully with error message', async () => {
      mockImageShouldFail = true
      const file = new File(['corrupt-data'], 'corrupt.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result).toEqual({
        width: 0,
        height: 0,
        valid: false,
        error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
      })
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('handles image with 0 dimensions gracefully as decode failure', async () => {
      mockNaturalWidth = 0
      mockNaturalHeight = 0
      const file = new File(['zero-dim'], 'zero.jpg', { type: 'image/jpeg' })

      const result = await validateImageDimensions(file)

      expect(result).toEqual({
        width: 0,
        height: 0,
        valid: false,
        error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
      })
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })
  })

  describe('compressImage', () => {
    it('downscales oversized image preserving aspect ratio and returns compressed File when smaller', async () => {
      mockNaturalWidth = 4000
      mockNaturalHeight = 3000

      // Original file: 3MB
      const originalFile = new File(['x'.repeat(3000)], 'photo.jpg', { type: 'image/jpeg' })
      Object.defineProperty(originalFile, 'size', { value: 3 * 1024 * 1024 })

      let canvasWidth = 0
      let canvasHeight = 0
      const drawImageMock = vi.fn()

      HTMLCanvasElement.prototype.getContext = vi.fn().mockImplementation(function (this: HTMLCanvasElement) {
        canvasWidth = this.width
        canvasHeight = this.height
        return {
          drawImage: drawImageMock,
        }
      })

      // Compressed blob: 1.2MB (< 3MB)
      const mockCompressedBlob = new Blob(['compressed-image'], { type: 'image/jpeg' })
      Object.defineProperty(mockCompressedBlob, 'size', { value: 1.2 * 1024 * 1024 })

      HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation(function (
        cb: (blob: Blob | null) => void
      ) {
        cb(mockCompressedBlob)
      })

      const compressedFile = await compressImage(originalFile, {
        maxDimension: 2048,
        quality: 0.85,
      })

      // 4000x3000 scaled down with max 2048:
      // width = 2048, height = Math.round(3000 * 2048 / 4000) = 1536
      expect(canvasWidth).toBe(2048)
      expect(canvasHeight).toBe(1536)
      expect(drawImageMock).toHaveBeenCalled()
      expect(compressedFile.name).toBe('photo.jpg')
      expect(compressedFile.size).toBeLessThan(originalFile.size)
      expect(compressedFile).not.toBe(originalFile)
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })

    it('downscales portrait oversized image preserving aspect ratio', async () => {
      mockNaturalWidth = 3000
      mockNaturalHeight = 6000

      const originalFile = new File(['portrait'], 'portrait.jpg', { type: 'image/jpeg' })
      Object.defineProperty(originalFile, 'size', { value: 4 * 1024 * 1024 })

      let canvasWidth = 0
      let canvasHeight = 0

      HTMLCanvasElement.prototype.getContext = vi.fn().mockImplementation(function (this: HTMLCanvasElement) {
        canvasWidth = this.width
        canvasHeight = this.height
        return {
          drawImage: vi.fn(),
        }
      })

      const mockCompressedBlob = new Blob(['compressed-portrait'], { type: 'image/jpeg' })
      Object.defineProperty(mockCompressedBlob, 'size', { value: 1 * 1024 * 1024 })

      HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation((cb) => {
        cb(mockCompressedBlob)
      })

      await compressImage(originalFile, { maxDimension: 2048 })

      // height = 2048, width = Math.round(3000 * 2048 / 6000) = 1024
      expect(canvasHeight).toBe(2048)
      expect(canvasWidth).toBe(1024)
    })

    it('returns original file if compressed blob is not smaller than original file', async () => {
      mockNaturalWidth = 800
      mockNaturalHeight = 600

      const originalFile = new File(['small'], 'small.jpg', { type: 'image/jpeg' })
      Object.defineProperty(originalFile, 'size', { value: 100 * 1024 }) // 100KB

      HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
        drawImage: vi.fn(),
      })

      // Compressed blob is larger or equal (120KB)
      const mockBlob = new Blob(['larger-blob'], { type: 'image/jpeg' })
      Object.defineProperty(mockBlob, 'size', { value: 120 * 1024 })

      HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation((cb) => {
        cb(mockBlob)
      })

      const result = await compressImage(originalFile)

      expect(result).toBe(originalFile)
      expect(result.size).toBe(100 * 1024)
    })

    it('returns original file gracefully if canvas context 2d is null', async () => {
      mockNaturalWidth = 800
      mockNaturalHeight = 600

      const originalFile = new File(['photo'], 'photo.png', { type: 'image/png' })
      HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null)

      const result = await compressImage(originalFile)

      expect(result).toBe(originalFile)
    })

    it('returns original file gracefully if toBlob returns null', async () => {
      mockNaturalWidth = 800
      mockNaturalHeight = 600

      const originalFile = new File(['photo'], 'photo.png', { type: 'image/png' })
      HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
        drawImage: vi.fn(),
      })
      HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation((cb) => {
        cb(null)
      })

      const result = await compressImage(originalFile)

      expect(result).toBe(originalFile)
    })

    it('returns original file gracefully if image fails to decode', async () => {
      mockImageShouldFail = true

      const originalFile = new File(['corrupt'], 'corrupt.png', { type: 'image/png' })

      const result = await compressImage(originalFile)

      expect(result).toBe(originalFile)
      expect(revokeObjectURLMock).toHaveBeenCalled()
    })
  })
})
