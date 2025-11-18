/**
 * AudioWorklet processor for converting audio to 16-bit PCM format
 * suitable for AssemblyAI streaming transcription
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096; // Process audio in chunks
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    const output = outputs[0];

    // Check if we have input
    if (input.length > 0) {
      const inputChannel = input[0]; // Use first channel (mono)

      // No output copying - silent processing only

      // Buffer the audio data
      for (let i = 0; i < inputChannel.length; i++) {
        this.buffer[this.bufferIndex] = inputChannel[i];
        this.bufferIndex++;

        // When buffer is full, convert to 16-bit PCM and send
        if (this.bufferIndex >= this.bufferSize) {
          this.sendPCMData();
          this.bufferIndex = 0;
        }
      }
    }

    return true; // Keep processor alive
  }

  sendPCMData() {
    // Convert float32 audio data to 16-bit PCM
    const pcmData = new Int16Array(this.bufferSize);

    for (let i = 0; i < this.bufferSize; i++) {
      // Clamp and convert to 16-bit PCM
      const sample = Math.max(-1, Math.min(1, this.buffer[i]));
      pcmData[i] = sample * 0x7fff;
    }

    // Send the PCM data to the main thread
    this.port.postMessage(pcmData);
  }
}

registerProcessor("pcm-processor", PCMProcessor);
