module resource_probe(input wire clk, input wire data, output reg observed);
  always @(posedge clk) observed <= data;
endmodule
