#include "device.hpp"

int main(int argc, char** argv) {
    try {
        original_r_board::require(argc == 4, "usage: candidate XCLBIN A4_INPUT DEVICE");
        const source_retention::Input input(argv[2]);
        source_retention::Device device(argv[1], original_g_board::number(argv[3]), input);
        for (unsigned repeat = 0; repeat < 4; ++repeat) device.run(input, repeat);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "RETENTION_REJECTED " << error.what() << '\n';
        return 1;
    }
}
