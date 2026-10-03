/**
 * Client-side image pre-validation and compression utilities.
 */

export const MIN_IMAGE_DIMENSION = 50
export const MAX_IMAGE_DIMENSION = 8192
export const DEFAULT_MAX_DIMENSION = 2048
export const DEFAULT_COMPRESSION_QUALITY = 0.85

export interface ImageDimensionValidationResult {
  width: number
  height: number
  valid: boolean
  error?: string
}

export interface CompressImageOptions {
  maxDimension?: number
  quality?: number
  maxSizeBytes?: number
}

/**
 * Validates image dimensions using browser Image and URL.createObjectURL.
 * Enforces minimum (50x50) and maximum (8192x8192) resolution limits.
 * Guarantees URL.revokeObjectURL is invoked on both decode success and failure.
 */
export function validateImageDimensions(
  file: File
): Promise<ImageDimensionValidationResult> {
  return new Promise((resolve) => {
    if (
      typeof URL === 'undefined' ||
      typeof URL.createObjectURL !== 'function' ||
      typeof Image === 'undefined'
    ) {
      return resolve({
        width: 0,
        height: 0,
        valid: false,
        error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
      })
    }

    let objectUrl: string
    try {
      objectUrl = URL.createObjectURL(file)
    } catch {
      return resolve({
        width: 0,
        height: 0,
        valid: false,
        error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
      })
    }

    const img = new Image()

    const cleanup = () => {
      try {
        if (typeof URL.revokeObjectURL === 'function') {
          URL.revokeObjectURL(objectUrl)
        }
      } catch {
        // ignore revocation errors
      }
    }

    img.onload = () => {
      cleanup()
      const width = img.naturalWidth || img.width
      const height = img.naturalHeight || img.height

      if (!width || !height || width <= 0 || height <= 0) {
        return resolve({
          width: 0,
          height: 0,
          valid: false,
          error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
        })
      }

      if (width < MIN_IMAGE_DIMENSION || height < MIN_IMAGE_DIMENSION) {
        return resolve({
          width,
          height,
          valid: false,
          error: `Image dimensions (${width}x${height}) are below minimum required resolution of ${MIN_IMAGE_DIMENSION}x${MIN_IMAGE_DIMENSION} pixels.`,
        })
      }

      if (width > MAX_IMAGE_DIMENSION || height > MAX_IMAGE_DIMENSION) {
        return resolve({
          width,
          height,
          valid: false,
          error: `Image dimensions (${width}x${height}) exceed maximum allowed resolution of ${MAX_IMAGE_DIMENSION}x${MAX_IMAGE_DIMENSION} pixels.`,
        })
      }

      return resolve({
        width,
        height,
        valid: true,
      })
    }

    img.onerror = () => {
      cleanup()
      return resolve({
        width: 0,
        height: 0,
        valid: false,
        error: 'Unable to decode image dimensions. Please verify the file is a valid image.',
      })
    }

    img.src = objectUrl
  })
}

/**
 * Downscales oversized images preserving aspect ratio and generates a compressed Blob.
 * If compression produces a smaller payload, returns a new File; otherwise returns original File.
 * Gracefully handles null context or canvas errors by returning original file.
 */
export function compressImage(
  file: File,
  options?: CompressImageOptions
): Promise<File> {
  const maxDimension = options?.maxDimension ?? DEFAULT_MAX_DIMENSION
  const quality = options?.quality ?? DEFAULT_COMPRESSION_QUALITY

  return new Promise<File>((resolve) => {
    if (
      typeof URL === 'undefined' ||
      typeof URL.createObjectURL !== 'function' ||
      typeof Image === 'undefined' ||
      typeof document === 'undefined'
    ) {
      return resolve(file)
    }

    let objectUrl: string
    try {
      objectUrl = URL.createObjectURL(file)
    } catch {
      return resolve(file)
    }

    const img = new Image()

    const cleanup = () => {
      try {
        if (typeof URL.revokeObjectURL === 'function') {
          URL.revokeObjectURL(objectUrl)
        }
      } catch {
        // ignore revocation errors
      }
    }

    img.onload = () => {
      cleanup()
      try {
        let width = img.naturalWidth || img.width
        let height = img.naturalHeight || img.height

        if (!width || !height || width <= 0 || height <= 0) {
          return resolve(file)
        }

        if (width > maxDimension || height > maxDimension) {
          if (width >= height) {
            height = Math.round((height * maxDimension) / width)
            width = maxDimension
          } else {
            width = Math.round((width * maxDimension) / height)
            height = maxDimension
          }
        }

        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height

        const ctx = canvas.getContext('2d')
        if (!ctx) {
          return resolve(file)
        }

        ctx.drawImage(img, 0, 0, width, height)

        const mimeType = file.type || 'image/jpeg'

        if (typeof canvas.toBlob !== 'function') {
          return resolve(file)
        }

        canvas.toBlob(
          (blob) => {
            if (blob && blob.size < file.size) {
              const compressedFile = new File([blob], file.name, {
                type: file.type || blob.type,
                lastModified: file.lastModified,
              })
              resolve(compressedFile)
            } else {
              resolve(file)
            }
          },
          mimeType,
          quality
        )
      } catch {
        resolve(file)
      }
    }

    img.onerror = () => {
      cleanup()
      resolve(file)
    }

    img.src = objectUrl
  })
}
