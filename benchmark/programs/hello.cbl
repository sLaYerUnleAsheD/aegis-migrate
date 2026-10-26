       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-MATH.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 NUM-A       PIC 9(2) VALUE 2.
       01 NUM-B       PIC 9(2) VALUE 2.
       01 CALC-SUM    PIC Z9.

       PROCEDURE DIVISION.
       BEGIN.
           DISPLAY "Hello, World!".
           ADD NUM-A NUM-B GIVING CALC-SUM.
           DISPLAY "2 + 2 = " CALC-SUM.
           STOP RUN.
