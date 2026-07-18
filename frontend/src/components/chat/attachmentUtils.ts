/**
 * attachmentUtils.ts — client-side attachment preparation for the hub chat.
 *
 * Images (except GIF) are re-encoded through a canvas before upload:
 *   - iPhone camera-roll photos routinely exceed the model's image limits
 *     (~5MB / 8000px on Anthropic) — downscaling to 2048px long edge keeps
 *     every real-world photo comfortably inside them.
 *   - iOS hands over HEIC files; drawing to a canvas and exporting JPEG
 *     converts them to a supported format for free.
 * GIFs and PDFs pass through untouched (canvas would flatten a GIF).
 */

export const MAX_IMAGE_EDGE_PX = 2048
const JPEG_QUALITY = 0.85

/** Mimes the backend whitelist accepts (mirror of core/hub_attachments.py). */
export const ACCEPTED_MIMES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
  'application/pdf',
])

export interface PreparedAttachment {
  blob: Blob
  filename: string
  kind: 'image' | 'pdf'
}

function isImage(file: File): boolean {
  return file.type.startsWith('image/')
}

/**
 * Prepare one file for upload. Downscales/re-encodes images as described
 * above; passes GIF/PDF through. Throws on unsupported types (including
 * image types the canvas cannot decode).
 */
export async function prepareAttachment(file: File): Promise<PreparedAttachment> {
  if (file.type === 'application/pdf') {
    return { blob: file, filename: file.name || 'document.pdf', kind: 'pdf' }
  }
  if (file.type === 'image/gif') {
    return { blob: file, filename: file.name || 'image.gif', kind: 'image' }
  }
  if (!isImage(file) && !ACCEPTED_MIMES.has(file.type)) {
    throw new Error(`Unsupported file type: ${file.type || 'unknown'}`)
  }

  // Any image type the browser can decode (incl. HEIC on iOS) → JPEG.
  const bitmap = await createImageBitmap(file)
  try {
    const scale = Math.min(1, MAX_IMAGE_EDGE_PX / Math.max(bitmap.width, bitmap.height))
    const width = Math.max(1, Math.round(bitmap.width * scale))
    const height = Math.max(1, Math.round(bitmap.height * scale))

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas unavailable')
    ctx.drawImage(bitmap, 0, 0, width, height)

    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error('Image encode failed'))),
        'image/jpeg',
        JPEG_QUALITY,
      )
    })
    const baseName = (file.name || 'photo').replace(/\.[^.]+$/, '')
    return { blob, filename: `${baseName}.jpg`, kind: 'image' }
  } finally {
    bitmap.close()
  }
}
