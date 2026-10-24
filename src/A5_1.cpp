#include <iostream>
#include <vector>
#include <cstdint>

  using std::cout;
  using std::endl;
  using std::cerr;
  using std::vector;

  class A5_1 {
    private:
      // Регистры R1 (19 бит), R2 (22 бита), R3 (23 бита)
      // Используем типы uint32_t, так как длины регистров не превышают 32 бит.
      uint32_t r1 = 0;
      uint32_t r2 = 0;
      uint32_t r3 = 0;

      // Маски для выделения конкретных бит (отсчет с 0 справа налево)
      const uint32_t R1_MASK = 0x7FFFF;  // 19 бит (0x7FFFF)
      const uint32_t R2_MASK = 0x3FFFFF; // 22 бита (0x3FFFFF)
      const uint32_t R3_MASK = 0x7FFFFF; // 23 бита (0x7FFFFF)

      // Возвращает мажоритарное значение (0 или 1) для трех управляющих бит
      uint32_t get_majority(uint32_t b1, uint32_t b2, uint32_t b3) {
        return (b1 + b2 + b3) >= 2 ? 1 : 0;
      }

    public:
      A5_1() = default;

      // Инициализация ключом сессии (64 бита) и номером кадра (22 бита)
      void initialize(uint64_t key, uint32_t frame) {
        r1 = 0; r2 = 0; r3 = 0;

        // 1. Сдвиг и XOR с 64 битами ключа
        for (int i = 0; i < 64; ++i) {
          uint32_t key_bit = (key >> i) & 1;
          step_all(key_bit);
        }

        // 2. Сдвиг и XOR с 22 битами номера кадра
        for (int i = 0; i < 22; ++i) {
          uint32_t frame_bit = (frame >> i) & 1;
          step_all(frame_bit);
        }

        // 3. 100 тактов работы вхолостую с мажоритарным тактированием (без выдачи битов)
        for (int i = 0; i < 100; ++i) {
          step_majority();
        }
      }

      // Тактирование всех регистров одновременно (используется при инициализации)
      void step_all(uint32_t external_bit) {
        // Вычисляем биты обратной связи (XOR полиномы для GSM)
        uint32_t fb1 = ((r1 >> 18) ^ (r1 >> 17) ^ (r1 >> 16) ^ (r1 >> 13)) & 1;
        uint32_t fb2 = ((r2 >> 21) ^ (r2 >> 20)) & 1;
        uint32_t fb3 = ((r3 >> 22) ^ (r3 >> 21) ^ (r3 >> 20) ^ (r3 >> 7)) & 1;

        // Сдвигаем влево на 1 и вставляем новый бит на место младшего (0-го) бита
        r1 = ((r1 << 1) | (fb1 ^ external_bit)) & R1_MASK;
        r2 = ((r2 << 1) | (fb2 ^ external_bit)) & R2_MASK;
        r3 = ((r3 << 1) | (fb3 ^ external_bit)) & R3_MASK;
      }

    // Тактирование по правилу большинства (основной рабочий режим)
    void step_majority() {
      // Управляющие биты: R1(8), R2(10), R3(10)
      uint32_t c1 = (r1 >> 8) & 1;
      uint32_t c2 = (r2 >> 10) & 1;
      uint32_t c3 = (r3 >> 10) & 1;

      uint32_t maj = get_majority(c1, c2, c3);

      // Регистр сдвигается, только если его управляющий бит совпадает с мажоритарным
      if (c1 == maj) {
        uint32_t fb1 = ((r1 >> 18) ^ (r1 >> 17) ^ (r1 >> 16) ^ (r1 >> 13)) & 1;
        r1 = ((r1 << 1) | fb1) & R1_MASK;
      }
      if (c2 == maj) {
        uint32_t fb2 = ((r2 >> 21) ^ (r2 >> 20)) & 1;
        r2 = ((r2 << 1) | fb2) & R2_MASK;
      }
      if (c3 == maj) {
        uint32_t fb3 = ((r3 >> 22) ^ (r3 >> 21) ^ (r3 >> 20) ^ (r3 >> 7)) & 1;
        r3 = ((r3 << 1) | fb3) & R3_MASK;
      }
    }

    // Генерация одного бита гаммы шифра
    uint32_t generate_bit() {
      step_majority();
      // Выходной бит — это XOR старших битов всех трех регистров
      return ((r1 >> 18) ^ (r2 >> 21) ^ (r3 >> 22)) & 1;
    }
  };

int main() {
    A5_1 cipher;

    // Пример секретного ключа (64 бита) и номера кадра GSM (22 бита)
    uint64_t secret_key = 0x123456789ABCDEF0ULL;
    uint32_t frame_number = 0x23456;

    cipher.initialize(secret_key, frame_number);

    std::cout << "Первые 20 бит сгенерированной гаммы: ";
    for (int i = 0; i < 20; ++i) {
        std::cout << cipher.generate_bit();
    }
    std::cout << std::endl;

    return 0;
}
